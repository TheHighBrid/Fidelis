"""Tests for F07 async queue end-to-end qualification harness."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "qualify-async-queue.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("qualify_async_queue", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load {SCRIPT_PATH}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class TestAsyncQueueQualification(unittest.TestCase):
    def test_fixture_end_to_end_qualification(self) -> None:
        mod = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            out_json = Path(tmp) / "f07_receipt.json"
            evidence_dir = Path(tmp) / "evidence"
            rc = mod.main(
                [
                    "--fixture",
                    "--evidence-dir",
                    str(evidence_dir),
                    "--output",
                    str(out_json),
                ]
            )
            self.assertEqual(rc, 0)
            self.assertTrue(out_json.is_file())
            receipt = json.loads(out_json.read_text(encoding="utf-8"))

        self.assertEqual(receipt["schema_version"], "fidelis.f07_async_qualification.v1")
        self.assertEqual(receipt["mode"], "fixture")
        self.assertEqual(receipt["evidence_level"], "E1_fixture_async_queue_tested")
        self.assertFalse(receipt["live_quality_verified"])
        self.assertFalse(receipt["e3_visual_accepted"])
        self.assertEqual(receipt["fixture_interrupt_calls"], 0)
        self.assertIn(receipt["fixture_prompt_submissions"], (3, 4))

        s1 = receipt["scenarios"]["responsiveness_and_apply"]
        self.assertEqual(s1["status"], "completed")
        self.assertEqual(s1["result_revision"], 2)
        self.assertEqual(s1["protected_pixel_mismatches"], 0)
        self.assertEqual(s1["unknown_pixel_mismatches"], 0)

        s2 = receipt["scenarios"]["scoped_cancel_no_global_interrupt"]
        self.assertEqual(s2["cancelled_status"], "cancelled")
        self.assertEqual(s2["unrelated_status"], "completed")
        self.assertEqual(s2["protected_pixel_mismatches"], 0)
        self.assertEqual(s2["unknown_pixel_mismatches"], 0)

        s3 = receipt["scenarios"]["restart_recovery_single_prompt"]
        self.assertEqual(s3["status_after_restart"], "interrupted")
        self.assertEqual(s3["final_status"], "completed")
        self.assertTrue(s3["single_prompt_id_preserved"])
        self.assertEqual(s3["before_prompt_id"], s3["after_prompt_id"])
        self.assertEqual(s3["protected_pixel_mismatches"], 0)
        self.assertEqual(s3["unknown_pixel_mismatches"], 0)

    def test_live_mode_fails_closed_when_worker_unreachable(self) -> None:
        mod = _load_module()
        with self.assertRaises(RuntimeError):
            mod.run_qualification(fixture=False, address="http://127.0.0.1:9")


if __name__ == "__main__":
    unittest.main()
