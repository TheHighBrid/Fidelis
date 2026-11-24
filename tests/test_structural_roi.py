"""Regression checks for source-grid locks and edge screening."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import numpy as np

from fidelis.postprocess.regions import RegionBlend
from fidelis.studio.http import dispatch
from fidelis.studio.store import JobStore, RevisionConflict
from fidelis.studio.structure import measure_region, propose_regions, validate_regions


class StructuralROITests(unittest.TestCase):
    def test_cli_locks_only_selected_rectangles_and_preserves_previous_locks(self):
        with tempfile.TemporaryDirectory() as workspace:
            store = JobStore(workspace)
            base = np.full((6, 8, 3), 30, dtype=np.uint8)
            texture = np.full_like(base, 210)
            fabric = np.ones((6, 8), dtype=np.float32)
            protected = np.zeros_like(fabric)
            protected[0, 0] = 1
            job = store.create(base, texture,
                               masks={"fabric": fabric, "confidence": fabric, "protected": protected},
                               blend=RegionBlend(fabric=1))
            script = Path(__file__).resolve().parents[1] / "scripts" / "structural-roi.py"
            cli = [sys.executable, str(script)]
            args = ["--workspace", workspace, "--job", job["id"], "--roi", "2", "1", "3", "4"]
            subprocess.run(cli + ["lock", *args, "--expected-revision", "1"],
                           capture_output=True, text=True, check=True)
            current = store.get(job["id"])
            self.assertEqual(current["artifacts"]["fabric"], job["artifacts"]["fabric"])
            self.assertEqual(current["last_structural_lock"]["rectangles"], [[2, 1, 3, 4]])
            with store.open_array(job["id"], "master") as master:
                np.testing.assert_array_equal(master[1:5, 2:5], base[1:5, 2:5])
                np.testing.assert_array_equal(master[0, 0], base[0, 0])
                np.testing.assert_array_equal(master[5, 7], texture[5, 7])
            result = subprocess.run(cli + ["inspect", *args, "--expected-revision", "2"],
                                    capture_output=True, text=True, check=True)
            self.assertEqual(json.loads(result.stdout)["regions"][0]["changed_pixels"], 0)
            stale = subprocess.run(cli + ["lock", *args, "--expected-revision", "1"],
                                   capture_output=True, text=True)
            self.assertEqual(stale.returncode, 2)
            invalid = subprocess.run(cli + ["lock", *args, "--roi", "7", "5", "2", "1",
                                             "--expected-revision", "2"], capture_output=True, text=True)
            self.assertEqual(invalid.returncode, 2)
            self.assertEqual(store.get(job["id"]), current)

    def test_shifted_edge_at_stripe_boundary_is_reported_on_equal_grids(self):
        base = np.zeros((6, 5, 3), dtype=np.uint8)
        base[2:] = 180
        shifted = np.zeros_like(base)
        shifted[3:] = 180
        report = measure_region(base, shifted, [0, 0, 5, 6], stripe_rows=2)
        self.assertEqual(report["changed_pixels"], 5)
        self.assertEqual(report["strong_edge_disagreements"], 10)

    def test_propose_regions_is_stripe_invariant_and_detects_dense_edges(self):
        base = np.full((64, 80, 3), 25, dtype=np.uint8)
        # Draw a high-contrast checkerboard-like logo cluster straddling row 32.
        for y in range(20, 44, 2):
            base[y, 20:44] = 240
        for x in range(20, 44, 2):
            base[20:44, x] = 240
        baseline = propose_regions(base, stripe_rows=64)
        self.assertFalse(baseline["semantic_proof"])
        self.assertEqual(baseline["dimensions"], [80, 64])
        self.assertGreaterEqual(len(baseline["proposals"]), 1)
        rect = baseline["proposals"][0]["rectangle"]
        self.assertLessEqual(rect[0], 20)
        self.assertLessEqual(rect[1], 20)
        self.assertGreaterEqual(rect[0] + rect[2], 44)
        self.assertGreaterEqual(rect[1] + rect[3], 44)
        validate_regions([p["rectangle"] for p in baseline["proposals"]], 80, 64)
        for rows in (1, 3, 7, 16, 32, 100):
            with self.subTest(stripe_rows=rows):
                self.assertEqual(propose_regions(base, stripe_rows=rows), baseline)

    def test_propose_regions_empty_on_flat_and_rejects_bad_arguments(self):
        flat = np.full((48, 48, 3), 120, dtype=np.uint8)
        report = propose_regions(flat)
        self.assertFalse(report["semantic_proof"])
        self.assertEqual(report["proposals"], [])
        with self.assertRaises(ValueError):
            propose_regions(flat, max_proposals=65)
        with self.assertRaises(ValueError):
            propose_regions(flat, stripe_rows=True)
        with self.assertRaises(ValueError):
            propose_regions(np.zeros((16, 16, 4), dtype=np.uint8))

    def test_cli_propose_with_target_scores_drift_and_feeds_lock(self):
        with tempfile.TemporaryDirectory() as workspace:
            store = JobStore(workspace)
            base = np.full((48, 48, 3), 20, dtype=np.uint8)
            for y in range(16, 32, 2):
                base[y, 16:32] = 235
            texture = np.full_like(base, 180)
            fabric = np.ones((48, 48), dtype=np.float32)
            job = store.create(
                base,
                texture,
                masks={"fabric": fabric, "confidence": fabric},
                blend=RegionBlend(fabric=1),
            )
            script = Path(__file__).resolve().parents[1] / "scripts" / "structural-roi.py"
            cli = [sys.executable, str(script)]
            proposed = subprocess.run(
                cli
                + [
                    "propose",
                    "--workspace",
                    workspace,
                    "--job",
                    job["id"],
                    "--expected-revision",
                    "1",
                    "--target",
                    "master",
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            payload = json.loads(proposed.stdout)
            self.assertFalse(payload["semantic_proof"])
            self.assertEqual(payload["target"], "master")
            self.assertGreaterEqual(len(payload["proposals"]), 1)
            first = payload["proposals"][0]
            self.assertGreater(first["changed_pixels"], 0)
            self.assertGreater(first["strong_edge_disagreements"], 0)
            # Propose is read-only and must not bump revision.
            self.assertEqual(store.get(job["id"])["revision"], 1)

            x, y, w, h = first["rectangle"]
            subprocess.run(
                cli
                + [
                    "lock",
                    "--workspace",
                    workspace,
                    "--job",
                    job["id"],
                    "--expected-revision",
                    "1",
                    "--roi",
                    str(x),
                    str(y),
                    str(w),
                    str(h),
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            rechecked = store.propose_structure(job["id"], expected_revision=2, target="master")
            self.assertEqual(rechecked["proposals"][0]["changed_pixels"], 0)
            self.assertEqual(rechecked["proposals"][0]["strong_edge_disagreements"], 0)
            stale = subprocess.run(
                cli
                + [
                    "propose",
                    "--workspace",
                    workspace,
                    "--job",
                    job["id"],
                    "--expected-revision",
                    "1",
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(stale.returncode, 2)

    def test_http_propose_structure_validates_revision_and_returns_proposals(self):
        import io
        from types import SimpleNamespace

        with tempfile.TemporaryDirectory() as workspace:
            store = JobStore(workspace)
            base = np.full((48, 48, 3), 20, dtype=np.uint8)
            for y in range(16, 32, 2):
                base[y, 16:32] = 235
            texture = np.full_like(base, 190)
            fabric = np.ones((48, 48), dtype=np.float32)
            job = store.create(
                base,
                texture,
                masks={"fabric": fabric, "confidence": fabric},
                blend=RegionBlend(fabric=1),
            )

            def _call(body):
                raw = json.dumps(body).encode("utf-8")
                responses = []
                headers = {
                    "Host": "127.0.0.1:8765",
                    "Content-Type": "application/json",
                    "Content-Length": str(len(raw)),
                }
                handler = SimpleNamespace(
                    command="POST",
                    path=f"/api/regions/jobs/{job['id']}/propose-structure",
                    client_address=("127.0.0.1", 50000),
                    headers=headers,
                    rfile=io.BytesIO(raw),
                    wfile=io.BytesIO(),
                    connection=SimpleNamespace(settimeout=lambda _t: None),
                    server=SimpleNamespace(server_port=8765),
                    send_response=lambda code: responses.append(code),
                    send_header=lambda _k, _v: None,
                    end_headers=lambda: None,
                )
                dispatch(handler, workspace)
                return responses[0], json.loads(handler.wfile.getvalue().decode("utf-8"))

            status_ok, ok_body = _call({"expected_revision": 1, "target": "texture", "max_proposals": 4})
            self.assertEqual(status_ok, 200)
            self.assertFalse(ok_body["semantic_proof"])
            self.assertGreaterEqual(len(ok_body["proposals"]), 1)

            status_bool, _ = _call({"expected_revision": True})
            self.assertEqual(status_bool, 400)

            status_stale, _ = _call({"expected_revision": 99})
            self.assertEqual(status_stale, 409)

            with self.assertRaises(RevisionConflict):
                store.propose_structure(job["id"], expected_revision=99)

    def test_propose_regions_localizes_clusters_on_tracked_fashion_crop(self):
        from PIL import Image

        crop_path = Path(__file__).resolve().parents[1] / "experiments" / "eval_crops" / "fashion_fabric_real.png"
        arr = np.asarray(Image.open(crop_path).convert("RGB"))
        report = propose_regions(arr, max_proposals=6)
        self.assertGreaterEqual(len(report["proposals"]), 2)
        for proposal in report["proposals"]:
            self.assertLess(proposal["pixels"], arr.shape[0] * arr.shape[1])
