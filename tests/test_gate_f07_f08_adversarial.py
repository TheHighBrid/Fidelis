"""Empirical adversarial challenge suite for Gate F07-A and Gate F08-A.

Validates:
- Gate F07-A: Queue capacity limits (413), cancel across lifecycles (queued, running,
  rejection during applying), local cancellation without global ComfyUI /interrupt,
  crash/restart recovery, and single-worker ownership locking.
- Gate F08-A: Crop coordinates out-of-bounds, negative, non-integer/nan/inf, odd
  dimensions up to 512x512, unscaled pixel extraction (no resampling vs preview),
  and revision mismatch rejection (stale revision -> 409).
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
from pathlib import Path
import sqlite3
import sys
import threading
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_comfy_backend as comfy_fixture
import test_region_http as http_fixture
from fidelis.postprocess.regions import RegionBlend
from fidelis.studio.comfy import ComfyTextureBackend
from fidelis.studio.generation import GenerationQueue, QueueFull
from fidelis.studio.http import dispatch
from fidelis.studio.inspection import MAX_CROP_SIDE, crop_bounds, native_crop
from fidelis.studio.store import JobStore, RevisionConflict


class GateF07AQueueAdversarialTests(unittest.TestCase):
    """Adversarial stress-testing of Gate F07-A (Generation Queue & Scoped Cancellation)."""

    def setUp(self):
        self.fixture = comfy_fixture.ComfyTests('test_success_cache_and_recipe_no_duplicate_submission')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = Path(self.fixture.temp.name) / 'async_adv'
        self.store = JobStore(Path(self.fixture.temp.name) / 'jobs_adv')
        self.queues = []
        self.addCleanup(self.close_queues)
        self.routes = []
        handler = self.fixture.server.RequestHandlerClass
        for method in ('do_POST', 'do_GET'):
            original = getattr(handler, method)
            routes = self.routes

            def tracked(request, original=original):
                routes.append((request.command, request.path))
                return original(request)

            setattr(handler, method, tracked)

    def close_queues(self):
        for queue in self.queues:
            queue.close()
        self.queues.clear()

    def make_queue(self, **kwargs):
        backend = ComfyTextureBackend(self.root / 'runs', self.fixture.backend.address,
                                     timeout=.5, poll_interval=.01)
        queue = GenerationQueue(self.root, self.store, comfy_fixture.BUNDLE, backend=backend, **kwargs)
        self.queues.append(queue)
        return queue

    def make_job(self, profile='luxury_apparel'):
        ones = np.ones((8, 12), np.float32)
        protected = np.zeros((8, 12), np.float32)
        protected[:, :3] = 1
        return self.store.create(self.fixture.source, self.fixture.source,
                                masks={'skin': ones, 'confidence': ones, 'protected': protected},
                                blend=RegionBlend(skin=1), profile=profile)

    def wait_status(self, queue, job, task, target_statuses, timeout=4):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            item = queue.get(job['id'], task['id'])
            if item['status'] in target_statuses:
                return item
            time.sleep(.01)
        self.fail(f"Task {task['id']} failed to reach {target_statuses}; final state: {item}")

    def test_queue_capacity_limit_and_http_413(self):
        """Stress-test queue capacity limit and verify HTTP 413 BudgetExceeded."""
        self.fixture.state['mode'] = 'pending'
        q = self.make_queue(capacity=2, max_records=8)
        server_root = self.store.root

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self): dispatch(self, server_root)
            def do_POST(self): dispatch(self, server_root)
            def log_message(self, *args): pass

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        server.region_store = self.store
        server.generation_queue = q
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(lambda: (server.shutdown(), server.server_close(), thread.join()))

        def post_enqueue(job_id, revision=1):
            req = Request(f"http://127.0.0.1:{server.server_port}/api/regions/jobs/{job_id}/generations",
                          data=json.dumps({'expected_revision': revision}).encode(),
                          headers={'Content-Type': 'application/json'})
            with urlopen(req, timeout=2) as response:
                return response.status, json.load(response)

        job1, job2, job3 = self.make_job(), self.make_job(), self.make_job()

        # Enqueue first task -> 202 Accepted (becomes running)
        status1, task1 = post_enqueue(job1['id'])
        self.assertEqual(status1, 202)
        self.wait_status(q, job1, task1, ('running',))

        # Enqueue second task -> 202 Accepted (becomes queued)
        status2, task2 = post_enqueue(job2['id'])
        self.assertEqual(status2, 202)
        self.assertEqual(q.get(job2['id'], task2['id'])['status'], 'queued')

        # Enqueue third task when capacity=2 -> MUST return HTTP 413
        with self.assertRaises(HTTPError) as caught:
            post_enqueue(job3['id'])
        self.assertEqual(caught.exception.code, 413)
        err_body = json.loads(caught.exception.read().decode())
        self.assertIn('queue/record limit', err_body['error'])

    def test_max_records_limit_and_http_413(self):
        """Verify that reaching max_records triggers QueueFull/413 even with 0 active tasks."""
        q = self.make_queue(capacity=2, max_records=2)
        job1, job2, job3 = self.make_job(), self.make_job(), self.make_job()

        # First completed task
        t1 = q.enqueue(job1['id'], 1)
        self.wait_status(q, job1, t1, ('completed',))

        # Second completed task
        t2 = q.enqueue(job2['id'], 1)
        self.wait_status(q, job2, t2, ('completed',))

        # 2 records stored. Active tasks = 0, but max_records = 2.
        with self.assertRaises(QueueFull):
            q.enqueue(job3['id'], 1)

    def test_invalid_queue_bounds_parameters(self):
        """Adversarial check on constructor validation bounds."""
        backend = ComfyTextureBackend(self.root / 'runs_invalid', self.fixture.backend.address)
        self.addCleanup(backend.close)
        invalid_args = [
            {'capacity': 0},
            {'capacity': 17},
            {'capacity': -1},
            {'capacity': 2.5},
            {'capacity': '2'},
            {'max_records': 3, 'capacity': 4},  # max_records < capacity
            {'max_records': 1001},
            {'deadline_seconds': 0},
            {'deadline_seconds': -10},
            {'deadline_seconds': 3601},
            {'deadline_seconds': 0.0},
        ]
        for kwargs in invalid_args:
            sub_root = self.root / f"sub_{time.time_ns()}"
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                GenerationQueue(sub_root, self.store, comfy_fixture.BUNDLE, backend=backend, **kwargs)

    def test_cancel_during_queued_lifecycle(self):
        """Cancel queued task: transitions to cancelled, never executes, remote_may_continue=False."""
        self.fixture.state['mode'] = 'pending'
        q = self.make_queue(capacity=3)
        job1, job2 = self.make_job(), self.make_job()

        # Task 1 occupies worker (running and submitted to Comfy)
        t1 = q.enqueue(job1['id'], 1)
        self.wait_status(q, job1, t1, ('running',))
        deadline = time.monotonic() + 3
        while self.fixture.state['submits'] < 1 and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertEqual(self.fixture.state['submits'], 1)

        # Task 2 is queued
        t2 = q.enqueue(job2['id'], 1)
        self.assertEqual(q.get(job2['id'], t2['id'])['status'], 'queued')

        # Cancel task 2 while queued
        cancelled = q.cancel(job2['id'], t2['id'])
        self.assertEqual(cancelled['status'], 'cancelled')
        self.assertFalse(cancelled['remote_may_continue'])
        self.assertTrue(cancelled['cancel_requested'])

        # Now finish task 1
        q.cancel(job1['id'], t1['id'])
        self.wait_status(q, job1, t1, ('cancelled',))

        # Wait a short moment to ensure worker loop had opportunity to process
        time.sleep(.1)

        # Verify task 2 was NEVER submitted to ComfyUI backend
        self.assertEqual(self.fixture.state['submits'], 1)
        self.assertEqual(q.get(job2['id'], t2['id'])['status'], 'cancelled')

        # Verify ComfyUI never received /interrupt
        self.assertFalse(any(path == '/interrupt' for _, path in self.routes))

    def test_cancel_during_running_lifecycle(self):
        """Cancel running task: remote_may_continue=True, backend stops without applying."""
        self.fixture.state['mode'] = 'pending'
        q = self.make_queue()
        job = self.make_job()

        task = q.enqueue(job['id'], 1)
        self.wait_status(q, job, task, ('running',))

        # Cancel while running
        cancelled = q.cancel(job['id'], task['id'])
        self.assertEqual(cancelled['status'], 'cancelled')
        self.assertTrue(cancelled['remote_may_continue'])

        # Worker catches cancellation in polling and marks interrupted/cancelled
        self.wait_status(q, job, task, ('cancelled', 'interrupted'))

        # Verify store revision was NOT incremented
        self.assertEqual(self.store.get(job['id'])['revision'], 1)

        # Verify ComfyUI never received /interrupt
        self.assertFalse(any(path == '/interrupt' for _, path in self.routes))

    def test_cancel_rejection_during_applying_atomic_boundary(self):
        """Rejection of cancel during 'applying' state (atomic commit boundary) -> 409 Conflict."""
        q = self.make_queue()
        job = self.make_job()

        ready = threading.Event()
        release = threading.Event()
        self.addCleanup(release.set)

        original_replace = self.store.replace_texture

        def mock_replace(*args, **kwargs):
            ready.set()
            release.wait(timeout=3)
            return original_replace(*args, **kwargs)

        with patch.object(self.store, 'replace_texture', side_effect=mock_replace):
            task = q.enqueue(job['id'], 1)
            self.assertTrue(ready.wait(timeout=2), "Did not enter replace_texture")

            # In applying state
            status = q.get(job['id'], task['id'])
            self.assertEqual(status['status'], 'applying')

            # Attempt cancel -> MUST raise RevisionConflict
            with self.assertRaises(RevisionConflict) as caught:
                q.cancel(job['id'], task['id'])
            self.assertIn("Result commit has started", str(caught.exception))

            # Release replace_texture to finish atomic commit
            release.set()
            final = self.wait_status(q, job, task, ('completed',))
            self.assertEqual(final['result_revision'], 2)
            self.assertEqual(self.store.get(job['id'])['revision'], 2)

    def test_local_cancellation_never_issues_comfy_interrupt(self):
        """Exhaustive check: across all queue workflows, no '/interrupt' route is ever called."""
        self.fixture.state['mode'] = 'pending'
        q = self.make_queue(capacity=3)
        job1, job2 = self.make_job(), self.make_job()

        t1 = q.enqueue(job1['id'], 1)
        t2 = q.enqueue(job2['id'], 1)

        # Cancel queued
        q.cancel(job2['id'], t2['id'])
        # Cancel running
        q.cancel(job1['id'], t1['id'])

        self.wait_status(q, job1, t1, ('cancelled',))

        # Check every HTTP call recorded by server handler
        for method, path in self.routes:
            self.assertNotEqual(path, '/interrupt', f"Global /interrupt was sent via {method} {path}!")
            if path == '/queue':
                self.assertNotEqual(method, 'POST', f"POST to /queue is forbidden!")

    def test_crash_recovery_running_and_applying_become_interrupted(self):
        """Crash recovery: tasks in 'running' and 'applying' become 'interrupted' and require explicit reconcile."""
        q1 = self.make_queue()
        job = self.make_job()

        # Enqueue and complete a task to create table
        t = q1.enqueue(job['id'], 1)
        self.wait_status(q1, job, t, ('completed',))
        q1.close()
        self.queues.remove(q1)

        # Artificially inject tasks in 'running' and 'applying' states into DB
        with sqlite3.connect(self.root / 'queue.sqlite3') as db:
            row = db.execute('SELECT record FROM tasks WHERE id=?', (t['id'],)).fetchone()
            base_record = json.loads(row[0])

            running_task = dict(base_record, id='fake-running-id', run_id='fake-run-1', status='running')
            applying_task = dict(base_record, id='fake-applying-id', run_id='fake-run-2', status='applying')

            db.execute('INSERT INTO tasks VALUES (?,?)', (running_task['id'], json.dumps(running_task)))
            db.execute('INSERT INTO tasks VALUES (?,?)', (applying_task['id'], json.dumps(applying_task)))

        # Start new queue instance on same root
        q2 = self.make_queue()

        # Both tasks must now be 'interrupted'
        rec_running = q2.get(job['id'], 'fake-running-id')
        rec_applying = q2.get(job['id'], 'fake-applying-id')

        self.assertEqual(rec_running['status'], 'interrupted')
        self.assertIn('Worker restarted', rec_running['message'])

        self.assertEqual(rec_applying['status'], 'interrupted')
        self.assertIn('Worker restarted', rec_applying['message'])

        # Neither task should have been resubmitted
        self.assertEqual(self.fixture.state['submits'], 1)

    def test_single_worker_directory_lock(self):
        """Only one GenerationQueue worker can own a queue root directory concurrently."""
        q1 = self.make_queue()
        other_backend = ComfyTextureBackend(self.root / 'runs', self.fixture.backend.address)
        self.addCleanup(other_backend.close)

        with self.assertRaises(RuntimeError) as caught:
            GenerationQueue(self.root, self.store, comfy_fixture.BUNDLE, backend=other_backend)
        self.assertIn('already owns this directory', str(caught.exception))

    def test_cross_job_cancellation_scoping(self):
        """Attempting to cancel a task belonging to Job A via Job B's endpoint must fail with 404."""
        self.fixture.state['mode'] = 'pending'
        q = self.make_queue()
        server_root = self.store.root

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self): dispatch(self, server_root)
            def do_POST(self): dispatch(self, server_root)
            def log_message(self, *args): pass

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        server.region_store = self.store
        server.generation_queue = q
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(lambda: (server.shutdown(), server.server_close(), thread.join()))

        job_a = self.make_job()
        job_b = self.make_job()

        task_a = q.enqueue(job_a['id'], 1)
        self.wait_status(q, job_a, task_a, ('running',))

        # Attempt to cancel task_a under job_b's URL
        req = Request(f"http://127.0.0.1:{server.server_port}/api/regions/jobs/{job_b['id']}/generations/{task_a['id']}/cancel",
                      data=b'{}', headers={'Content-Type': 'application/json'})
        with self.assertRaises(HTTPError) as caught:
            with urlopen(req, timeout=2):
                pass
        self.assertEqual(caught.exception.code, 404)
        err = json.loads(caught.exception.read().decode())
        self.assertIn('not found', err['error'].lower())


class GateF08ANativeCropAdversarialTests(unittest.TestCase):
    """Adversarial stress-testing of Gate F08-A (Native Crop Inspection)."""

    def setUp(self):
        self.fixture = http_fixture.HttpTests('test_import_reopen_reblend_export_and_stale_write')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.store = JobStore(self.fixture.temp.name)
        self.fixture.server.region_store = self.store

    def create_job(self, base_arr=None):
        base = self.fixture.base if base_arr is None else base_arr
        texture = 255 - base
        confidence = np.ones(base.shape[:2], np.float32)
        protected = np.zeros(base.shape[:2], np.float32)
        protected[:, :3] = 1
        return self.store.create(base, texture,
                                masks={'skin': confidence, 'confidence': confidence, 'protected': protected},
                                blend=RegionBlend(skin=1, edge_protection=0))

    def request_crop(self, job_id, role='master', **query_params):
        query = {'role': role, **query_params}
        path = f"/api/regions/jobs/{job_id}/crop?{urlencode(query)}"
        return self.fixture.request(path)

    def decode_png(self, raw_bytes):
        with Image.open(io.BytesIO(raw_bytes)) as image:
            return np.array(image)

    def test_out_of_bounds_crop_coordinates_rejected(self):
        """Reject crops extending past image boundaries (e.g. x+w > W, y+h > H)."""
        # Base dimensions (H=8, W=12)
        job = self.create_job()
        H, W = self.fixture.base.shape[:2]

        out_of_bounds_cases = [
            # x + width > W
            {'revision': 1, 'x': 10, 'y': 0, 'width': 5, 'height': 4},  # 10 + 5 = 15 > 12
            {'revision': 1, 'x': 12, 'y': 0, 'width': 1, 'height': 1},  # x == W
            {'revision': 1, 'x': 13, 'y': 0, 'width': 1, 'height': 1},  # x > W
            # y + height > H
            {'revision': 1, 'x': 0, 'y': 6, 'width': 4, 'height': 4},   # 6 + 4 = 10 > 8
            {'revision': 1, 'x': 0, 'y': 8, 'width': 1, 'height': 1},   # y == H
            {'revision': 1, 'x': 0, 'y': 9, 'width': 1, 'height': 1},   # y > H
            # Both out of bounds
            {'revision': 1, 'x': 11, 'y': 7, 'width': 2, 'height': 2},  # 11+2=13>12, 7+2=9>8
        ]

        for params in out_of_bounds_cases:
            with self.subTest(params=params), self.assertRaises(HTTPError) as caught:
                self.request_crop(job['id'], **params)
            self.assertEqual(caught.exception.code, 400)

        # Boundary checks that MUST pass
        # Exact full image
        status, body, headers = self.request_crop(job['id'], revision=1, x=0, y=0, width=W, height=H)
        self.assertEqual(status, 200)
        self.assertEqual(self.decode_png(body).shape, (H, W, 3))

        # Bottom-right corner pixel
        status, body, headers = self.request_crop(job['id'], revision=1, x=W - 1, y=H - 1, width=1, height=1)
        self.assertEqual(status, 200)
        self.assertEqual(self.decode_png(body).shape, (1, 1, 3))

    def test_negative_and_zero_coordinates_rejected(self):
        """Reject negative coordinates or zero dimensions."""
        job = self.create_job()
        invalid_cases = [
            {'revision': 1, 'x': -1, 'y': 0, 'width': 4, 'height': 4},
            {'revision': 1, 'x': 0, 'y': -1, 'width': 4, 'height': 4},
            {'revision': 1, 'x': -10, 'y': -10, 'width': 4, 'height': 4},
            {'revision': 1, 'x': 0, 'y': 0, 'width': 0, 'height': 4},
            {'revision': 1, 'x': 0, 'y': 0, 'width': 4, 'height': 0},
            {'revision': 1, 'x': 0, 'y': 0, 'width': -1, 'height': 4},
        ]
        for params in invalid_cases:
            with self.subTest(params=params), self.assertRaises(HTTPError) as caught:
                self.request_crop(job['id'], **params)
            self.assertEqual(caught.exception.code, 400)

    def test_non_integer_nan_inf_inputs_rejected(self):
        """Reject non-integer, NaN, Inf, and float coordinates."""
        job = self.create_job()
        malformed_queries = [
            {'revision': 1, 'x': '1.5', 'y': 0, 'width': 4, 'height': 4},
            {'revision': 1, 'x': 0, 'y': '2.8', 'width': 4, 'height': 4},
            {'revision': 1, 'x': 0, 'y': 0, 'width': '4.0', 'height': 4},
            {'revision': 1, 'x': 0, 'y': 0, 'width': 4, 'height': '4.5'},
            {'revision': 1, 'x': 'nan', 'y': 0, 'width': 4, 'height': 4},
            {'revision': 1, 'x': 'inf', 'y': 0, 'width': 4, 'height': 4},
            {'revision': 1, 'x': '-inf', 'y': 0, 'width': 4, 'height': 4},
            {'revision': 1, 'x': 'null', 'y': 0, 'width': 4, 'height': 4},
            {'revision': 1, 'x': 'true', 'y': 0, 'width': 4, 'height': 4},
        ]
        for params in malformed_queries:
            with self.subTest(params=params), self.assertRaises(HTTPError) as caught:
                self.request_crop(job['id'], **params)
            self.assertEqual(caught.exception.code, 400)

        # Also test Python crop_bounds unit directly
        test_shape = (100, 100, 3)
        for bad_val in (True, False, 1.5, 0.0, '5', np.float64(3)):
            with self.assertRaises(ValueError):
                crop_bounds(test_shape, x=bad_val, y=0, width=10, height=10)

    def test_odd_dimensions_and_max_crop_size(self):
        """Test odd crop dimensions and upper bound of 512x512."""
        # Create a large patterned image (800 x 900)
        rng = np.random.default_rng(42)
        large_base = rng.integers(0, 256, (800, 900, 3), dtype=np.uint8)
        job = self.create_job(large_base)

        odd_dimensions = [
            (1, 1),
            (3, 7),
            (17, 31),
            (127, 129),
            (255, 257),
            (511, 511),
            (MAX_CROP_SIDE, MAX_CROP_SIDE),  # 512 x 512
        ]

        for w, h in odd_dimensions:
            with self.subTest(w=w, h=h):
                status, body, headers = self.request_crop(job['id'], role='base',
                                                         revision=1, x=10, y=20, width=w, height=h)
                self.assertEqual(status, 200)
                arr = self.decode_png(body)
                self.assertEqual(arr.shape, (h, w, 3))
                # Verify exact pixel match
                np.testing.assert_array_equal(arr, large_base[20:20 + h, 10:10 + w])

        # Exceeding MAX_CROP_SIDE (513) MUST fail
        with self.assertRaises(HTTPError) as caught:
            self.request_crop(job['id'], role='base', revision=1, x=0, y=0, width=513, height=100)
        self.assertEqual(caught.exception.code, 400)

        with self.assertRaises(HTTPError) as caught:
            self.request_crop(job['id'], role='base', revision=1, x=0, y=0, width=100, height=513)
        self.assertEqual(caught.exception.code, 400)

    def test_unscaled_pixel_extraction_no_resampling(self):
        """Verify unscaled pixel extraction: crop never resamples, while preview downsamples."""
        # Create image with > 1,000,000 pixels (e.g. 1100 x 1200 = 1.32 MP)
        # Unique deterministic pattern: every pixel coordinate has distinct RGB
        H, W = 1100, 1200
        y_coords, x_coords = np.indices((H, W))
        pattern_base = np.stack([
            (x_coords * 13 + y_coords * 7) % 256,
            (x_coords * 17 + y_coords * 23) % 256,
            (x_coords * 29 + y_coords * 37) % 256,
        ], axis=-1).astype(np.uint8)

        job = self.create_job(pattern_base)

        # 1. Inspect preview endpoint: must be downsampled due to MAX_PREVIEW_PIXELS
        preview_res = self.fixture.request(f"/api/regions/jobs/{job['id']}/preview?role=base&revision=1")
        self.assertEqual(preview_res[0], 200)
        preview_img = self.decode_png(preview_res[1])
        self.assertLess(preview_img.shape[0], H)
        self.assertLess(preview_img.shape[1], W)

        # 2. Inspect native crop endpoint: MUST be exact unscaled pixels
        crop_x, crop_y, crop_w, crop_h = 333, 444, 175, 215
        crop_res = self.request_crop(job['id'], role='base', revision=1,
                                     x=crop_x, y=crop_y, width=crop_w, height=crop_h)
        self.assertEqual(crop_res[0], 200)
        self.assertEqual(crop_res[2]['X-Fidelis-Revision'], '1')
        self.assertEqual(crop_res[2]['X-Fidelis-Crop'], f"{crop_x},{crop_y},{crop_w},{crop_h}")
        self.assertEqual(crop_res[2]['Cache-Control'], 'no-store')

        native_img = self.decode_png(crop_res[1])
        self.assertEqual(native_img.shape, (crop_h, crop_w, 3))

        # Check exact equality for every single pixel in the crop
        expected_slice = pattern_base[crop_y:crop_y + crop_h, crop_x:crop_x + crop_w]
        np.testing.assert_array_equal(native_img, expected_slice)

    def test_revision_mismatch_rejection_http_409(self):
        """Reject stale or mismatched revision with HTTP 409 RevisionConflict."""
        job = self.create_job()
        self.assertEqual(job['revision'], 1)

        # Current revision 1 succeeds
        status, _, _ = self.request_crop(job['id'], revision=1, x=0, y=0, width=4, height=4)
        self.assertEqual(status, 200)

        # Non-existent future revision -> 409
        with self.assertRaises(HTTPError) as caught:
            self.request_crop(job['id'], revision=2, x=0, y=0, width=4, height=4)
        self.assertEqual(caught.exception.code, 409)
        err = json.loads(caught.exception.read().decode())
        self.assertIn('revision changed', err['error'])

        # Bump revision to 2 by reblending
        self.store.reblend(job['id'], expected_revision=1, blend=RegionBlend(skin=0.5))
        self.assertEqual(self.store.get(job['id'])['revision'], 2)

        # Revision 1 is now STALE -> MUST return 409
        with self.assertRaises(HTTPError) as caught:
            self.request_crop(job['id'], revision=1, x=0, y=0, width=4, height=4)
        self.assertEqual(caught.exception.code, 409)
        err_stale = json.loads(caught.exception.read().decode())
        self.assertIn('revision changed', err_stale['error'])

        # Revision 2 is now current -> MUST return 200
        status2, _, headers2 = self.request_crop(job['id'], revision=2, x=0, y=0, width=4, height=4)
        self.assertEqual(status2, 200)
        self.assertEqual(headers2['X-Fidelis-Revision'], '2')

        # Revision <= 0 is invalid argument -> 400
        with self.assertRaises(HTTPError) as caught:
            self.request_crop(job['id'], revision=0, x=0, y=0, width=4, height=4)
        self.assertEqual(caught.exception.code, 400)

    def test_crop_query_parameter_strictness_and_extra_params(self):
        """Strict query parameter validation: extra, missing, or duplicate parameters rejected."""
        job = self.create_job()
        base_query = {'role': 'base', 'revision': 1, 'x': 0, 'y': 0, 'width': 4, 'height': 4}

        # Extra parameters
        with self.assertRaises(HTTPError) as caught:
            self.request_crop(job['id'], **base_query, extra_param='malicious')
        self.assertEqual(caught.exception.code, 400)

        # Missing parameters
        for key in ('role', 'revision', 'x', 'y', 'width', 'height'):
            missing = dict(base_query)
            del missing[key]
            path = f"/api/regions/jobs/{job['id']}/crop?{urlencode(missing)}"
            with self.subTest(missing_key=key), self.assertRaises(HTTPError) as caught:
                self.fixture.request(path)
            self.assertEqual(caught.exception.code, 400)

        # Duplicate parameters in query string
        duplicate_query = urlencode(base_query) + '&role=master'
        with self.assertRaises(HTTPError) as caught:
            self.fixture.request(f"/api/regions/jobs/{job['id']}/crop?{duplicate_query}")
        self.assertEqual(caught.exception.code, 400)

    def test_crop_unsupported_role_and_path_traversal(self):
        """Reject unsupported roles and directory traversal attempts."""
        job = self.create_job()
        bad_roles = [
            '../../../../etc/passwd',
            'protected',
            'confidence',
            'skin',
            'unknown',
            '',
            'master/../base',
        ]
        for role in bad_roles:
            with self.subTest(role=role), self.assertRaises(HTTPError) as caught:
                self.request_crop(job['id'], role=role, revision=1, x=0, y=0, width=4, height=4)
            self.assertEqual(caught.exception.code, 400)


if __name__ == '__main__':
    unittest.main()
