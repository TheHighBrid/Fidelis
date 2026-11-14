"""Regression checks for source-grid locks and edge screening."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import numpy as np

from fidelis.postprocess.regions import RegionBlend
from fidelis.studio.store import JobStore
from fidelis.studio.structure import measure_region


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
