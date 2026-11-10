"""Durable async queue tests using controlled HTTP responses, not GPU inference."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sqlite3
import socket
import subprocess
import sys
import signal
import threading
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import numpy as np

import test_comfy_backend as comfy_fixture
BUNDLE = comfy_fixture.BUNDLE
from fidelis.postprocess.regions import RegionBlend
from fidelis.studio.comfy import ComfyTextureBackend, GenerationCancelled
from fidelis.studio.generation import GenerationQueue, QueueFull
from fidelis.studio.http import dispatch
from fidelis.studio.store import JobStore, RevisionConflict


class GenerationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = comfy_fixture.ComfyTests('test_success_cache_and_recipe_no_duplicate_submission')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = Path(self.fixture.temp.name) / 'async'
        self.store = JobStore(Path(self.fixture.temp.name) / 'jobs')
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

    def queue(self, **kwargs):
        backend = ComfyTextureBackend(self.root/'runs', self.fixture.backend.address,
                                     timeout=.5, poll_interval=.01)
        queue = GenerationQueue(self.root, self.store, BUNDLE, backend=backend, **kwargs)
        self.queues.append(queue)
        return queue

    def job(self, profile='luxury_apparel'):
        ones = np.ones((8,12), np.float32)
        protected = np.zeros((8,12), np.float32); protected[:,:3] = 1
        return self.store.create(self.fixture.source, self.fixture.source,
                    masks={'skin':ones, 'confidence':ones, 'protected':protected},
                    blend=RegionBlend(skin=1), profile=profile)

    def wait(self, queue, job, task, status):
        deadline = time.monotonic()+4
        while time.monotonic()<deadline:
            item = queue.get(job['id'], task['id'])
            if item['status'] in status:
                return item
            time.sleep(.01)
        self.fail('Timed out: '+repr(item))

    def submitted(self):
        deadline = time.monotonic()+3
        while self.fixture.state['submits'] < 1 and time.monotonic()<deadline:
            time.sleep(.01)
        self.assertEqual(self.fixture.state['submits'], 1)

    def test_success_applies_once_and_preserves_protected_pixels(self):
        q=self.queue(); job=self.job(); task=q.enqueue(job['id'],1)
        result=self.wait(q,job,task,('completed',))
        self.assertEqual(result['result_revision'],2)
        self.assertEqual(self.fixture.state['submits'],1)
        with self.store.open_array(job['id'],'master') as master:
            np.testing.assert_array_equal(master[:,:3],self.fixture.source[:,:3])
            np.testing.assert_array_equal(master[:,3:],self.fixture.output[:,3:])
        self.assertNotIn('bundle',q.list(job['id'])[0])
        self.assertNotIn('backend_address',result)
        self.assertFalse(result['live_quality_verified'])

    def test_queued_cancel_bounds_and_no_unrelated_remote_interrupt(self):
        self.fixture.state['mode']='pending'
        q=self.queue(capacity=2); first=self.job(); second=self.job(); third=self.job()
        a=q.enqueue(first['id'],1); self.submitted()
        b=q.enqueue(second['id'],1)
        with self.assertRaises(QueueFull):q.enqueue(third['id'],1)
        with self.assertRaises(RevisionConflict):q.enqueue(first['id'],1)
        cancelled=q.cancel(second['id'],b['id'])
        self.assertFalse(cancelled['remote_may_continue'])
        q.cancel(first['id'],a['id'])
        self.wait(q,first,a,('cancelled',))
        # An unrelated fixture prompt must not be deleted/interrupted.
        self.assertIn('prompt-1',self.fixture.state['history'])
        self.assertFalse(any(route in ('/interrupt','/queue') and method=='POST' for method,route in self.routes))
        self.assertEqual(self.fixture.state['submits'],1)
        self.assertEqual(self.store.get(first['id'])['revision'],1)

    def test_running_cancel_cannot_apply_late_result(self):
        q=self.queue(); job=self.job(); ready=threading.Event(); release=threading.Event()
        self.addCleanup(release.set)
        def late(*args,**kwargs):
            ready.set();release.wait(2)
            return self.fixture.output,{'prompt_id':'owned','live_quality_verified':False}
        with patch.object(q.backend,'run',side_effect=late):
            task=q.enqueue(job['id'],1);self.assertTrue(ready.wait(2))
            self.assertTrue(q.cancel(job['id'],task['id'])['remote_may_continue'])
            release.set()
            next_job=self.job();next_task=q.enqueue(next_job['id'],1)
            self.wait(q,next_job,next_task,('completed',))
            self.assertEqual(self.store.get(job['id'])['revision'],1)
        self.assertEqual(self.store.get(job['id'])['revision'],1)

    def test_cancel_is_job_scoped_and_strict_and_revision_fail_closed(self):
        self.fixture.state['mode']='pending';q=self.queue();job=self.job();other=self.job()
        task=q.enqueue(job['id'],1);self.submitted()
        with self.assertRaises(KeyError):q.cancel(other['id'],task['id'])
        with self.assertRaises(ValueError):q.enqueue(other['id'],True)
        with self.assertRaises(RevisionConflict):q.enqueue(other['id'],2)
        with self.assertRaises(ValueError):q.enqueue(self.job('packshot_strict')['id'],1)
        self.store.reblend(job['id'],expected_revision=1,blend=RegionBlend(skin=.5))
        self.fixture.state['mode']='success'
        self.assertEqual(self.wait(q,job,task,('failed',))['error'],'RevisionConflict')
        self.assertEqual(self.store.get(job['id'])['revision'],2)

    def test_restart_requires_explicit_reconcile_and_does_not_resubmit(self):
        self.fixture.state['mode']='pending';q=self.queue();job=self.job()
        task=q.enqueue(job['id'],1);self.submitted()
        q.close();self.queues.remove(q)
        q=self.queue()
        self.assertEqual(q.get(job['id'],task['id'])['status'],'interrupted')
        self.fixture.state['mode']='success'
        q.resume(job['id'],task['id'])
        self.wait(q,job,task,('completed',))
        self.assertEqual(self.fixture.state['submits'],1)

    def test_queued_task_survives_restart_without_restarting_active_task(self):
        self.fixture.state['mode']='pending';q=self.queue();first=self.job();second=self.job()
        active=q.enqueue(first['id'],1);self.submitted();queued=q.enqueue(second['id'],1)
        q.close();self.queues.remove(q)
        self.fixture.state['mode']='success';q=self.queue()
        self.wait(q,second,queued,('completed',))
        self.assertEqual(q.get(first['id'],active['id'])['status'],'interrupted')
        self.assertEqual(self.fixture.state['submits'],2)

    def test_cancel_after_queued_resume_retains_remote_warning(self):
        self.fixture.state['mode']='pending';q=self.queue(deadline_seconds=.05);job=self.job()
        task=q.enqueue(job['id'],1);self.wait(q,job,task,('waiting',))
        with q.lock:
            q.resume(job['id'],task['id'])
            result=q.cancel(job['id'],task['id'])
        self.assertTrue(result['remote_may_continue'])
        self.assertEqual(result['status'],'cancelled')
        self.assertEqual(self.fixture.state['submits'],1)

    def test_ambiguous_submit_and_timeout_preserve_run_identity(self):
        self.fixture.state['mode']='ambiguous';q=self.queue(deadline_seconds=.1);job=self.job()
        task=q.enqueue(job['id'],1)
        self.wait(q,job,task,('needs_review',))
        self.fixture.state['mode']='success';q.resume(job['id'],task['id'])
        self.wait(q,job,task,('completed',))
        self.assertEqual(self.fixture.state['submits'],1)
        self.fixture.state['mode']='pending';second=self.job();pending=q.enqueue(second['id'],1)
        result=self.wait(q,second,pending,('waiting',))
        self.assertTrue(result['remote_may_continue'])
        self.fixture.state['mode']='success';q.resume(second['id'],pending['id'])
        self.wait(q,second,pending,('completed',))
        self.assertEqual(self.fixture.state['submits'],2)

    def test_applying_is_a_commit_boundary_and_status_remains_responsive(self):
        q=self.queue();job=self.job();ready=threading.Event();release=threading.Event()
        original=self.store.replace_texture
        def applying(*args,**kwargs):
            ready.set();release.wait(2);return original(*args,**kwargs)
        self.addCleanup(release.set)
        with patch.object(self.store,'replace_texture',side_effect=applying):
            task=q.enqueue(job['id'],1);self.assertTrue(ready.wait(2))
            start=time.monotonic()
            self.assertEqual(q.get(job['id'],task['id'])['status'],'applying')
            self.assertLess(time.monotonic()-start,.3)
            with self.assertRaises(RevisionConflict):q.cancel(job['id'],task['id'])
            release.set();self.wait(q,job,task,('completed',))

    def test_single_worker_ownership_and_record_limit(self):
        q=self.queue(capacity=1,max_records=1)
        other_backend=ComfyTextureBackend(self.root/'runs',self.fixture.backend.address)
        self.addCleanup(other_backend.close)
        with self.assertRaisesRegex(RuntimeError,'already owns'):
            GenerationQueue(self.root,self.store,BUNDLE,backend=other_backend)
        job=self.job();task=q.enqueue(job['id'],1);self.wait(q,job,task,('completed',))
        with self.assertRaises(QueueFull):q.enqueue(self.job()['id'],1)

    def test_hard_restart_marks_running_and_applying_interrupted(self):
        q=self.queue();job=self.job();task=q.enqueue(job['id'],1)
        self.wait(q,job,task,('completed',));q.close();self.queues.remove(q)
        with sqlite3.connect(self.root/'queue.sqlite3') as db:
            item=json.loads(db.execute('SELECT record FROM tasks').fetchone()[0])
            item['status']='applying'
            db.execute('UPDATE tasks SET record=?',(json.dumps(item),))
        q=self.queue()
        self.assertEqual(q.get(job['id'],task['id'])['status'],'interrupted')
        # A crashed apply may already have committed. Stale revision fails closed.
        q.resume(job['id'],task['id']);self.wait(q,job,task,('failed',))
        self.assertEqual(self.store.get(job['id'])['revision'],2)
        self.assertEqual(self.fixture.state['submits'],1)

    def test_poll_transport_error_preserves_unresolved_run(self):
        self.fixture.state['mode']='pending';q=self.queue();job=self.job()
        original=q.backend._json
        def offline(method,route,**kwargs):
            if route.startswith('/history/'):
                raise OSError('Fixture polling connection lost')
            return original(method,route,**kwargs)
        with patch.object(q.backend,'_json',side_effect=offline):
            task=q.enqueue(job['id'],1)
            result=self.wait(q,job,task,('needs_review',))
        self.assertTrue(result['remote_may_continue'])
        self.fixture.state['mode']='success';q.resume(job['id'],task['id'])
        self.wait(q,job,task,('completed',))
        self.assertEqual(self.fixture.state['submits'],1)

    def test_backend_cancellation_before_submission_and_during_poll(self):
        with self.assertRaises(GenerationCancelled):
            self.fixture.backend.run(self.fixture.source,BUNDLE,cancelled=lambda:True)
        self.assertEqual(self.fixture.state['submits'],0)
        self.fixture.state['mode']='pending'
        with self.assertRaises(GenerationCancelled):
            self.fixture.backend.run(self.fixture.source,BUNDLE,
                              cancelled=lambda:self.fixture.state['submits']>0)
        self.assertEqual(self.fixture.state['submits'],1)
        self.assertNotIn(('POST','/interrupt'),self.routes)

    def test_real_server_startup_configures_optional_worker(self):
        self.fixture.state['mode']='pending'
        workflow=Path(self.fixture.temp.name)/'workflow.json'
        workflow.write_text(json.dumps(BUNDLE))
        job=self.job()
        with socket.socket() as probe:
            probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
        process=subprocess.Popen([sys.executable,str(Path(__file__).resolve().parents[1]/'scripts/web-ui.py'),
                  '--port',str(port),'--region-workspace',str(self.store.root),
                  '--texture-workflow',str(workflow),'--generation-root',str(self.root),
                  '--comfy-address',self.fixture.backend.address],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        def stop():
            if process.poll() is None:
                process.send_signal(signal.SIGINT)
                try:process.wait(timeout=5)
                except subprocess.TimeoutExpired:process.kill();process.wait()
        self.addCleanup(stop)
        address=f'http://127.0.0.1:{port}'
        deadline=time.monotonic()+5
        while True:
            try:
                with urlopen(address+'/api/regions/jobs',timeout=.5) as response:
                    self.assertTrue(json.load(response)['generation_enabled'])
                break
            except OSError:
                if time.monotonic()>deadline:self.fail('Server did not become ready')
                time.sleep(.03)
        path=f"/api/regions/jobs/{job['id']}/generations"
        req=Request(address+path,data=json.dumps({'expected_revision':1}).encode(),headers={'Content-Type':'application/json'})
        with urlopen(req,timeout=1) as response:
            self.assertEqual(response.status,202);task=json.load(response)
        self.submitted()
        with urlopen(address+'/regions',timeout=1) as response:
            html=response.read();self.assertIn(b'Cancel local task',html)
        req=Request(address+path+'/'+task['id']+'/cancel',data=b'{}',headers={'Content-Type':'application/json'})
        with urlopen(req,timeout=1) as response:self.assertEqual(json.load(response)['status'],'cancelled')
        stop()
        self.assertEqual(process.returncode,0)
        self.assertEqual(self.store.get(job['id'])['revision'],1)

    def test_http_202_status_cancel_and_origin_ownership_checks(self):
        self.fixture.state['mode']='pending';q=self.queue();root=self.store.root
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):dispatch(self,root)
            def do_POST(self):dispatch(self,root)
            def log_message(self,*args):pass
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        server.region_store=self.store;server.generation_queue=q
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        def stop():server.shutdown();server.server_close();thread.join()
        self.addCleanup(stop)
        def request(path,data=None,headers=None):
            req=Request(f'http://127.0.0.1:{server.server_port}'+path,
                 data=None if data is None else json.dumps(data).encode(),
                 headers={'Content-Type':'application/json',**(headers or {})})
            with urlopen(req,timeout=1) as response:return response.status,json.load(response)
        job=self.job();other=self.job();path=f"/api/regions/jobs/{job['id']}/generations"
        status,task=request(path,{'expected_revision':1});self.assertEqual(status,202);self.submitted()
        self.assertTrue(request('/api/regions/jobs')[1]['generation_enabled'])
        self.assertEqual(request(path+'/'+task['id'])[1]['status'],'running')
        with self.assertRaises(HTTPError) as caught:
            request(f"/api/regions/jobs/{other['id']}/generations/{task['id']}/cancel",{})
        self.assertEqual(caught.exception.code,404)
        with self.assertRaises(HTTPError) as caught:request(path,{}, {'Origin':'http://elsewhere'})
        self.assertEqual(caught.exception.code,403)
        self.assertEqual(request(path+'/'+task['id']+'/cancel',{})[1]['status'],'cancelled')
        self.assertEqual(request('/api/regions/jobs')[0],200)
        server.generation_queue=None
        with self.assertRaises(HTTPError) as caught:request(path,{'expected_revision':1})
        self.assertEqual(caught.exception.code,503)


if __name__=='__main__':unittest.main()
