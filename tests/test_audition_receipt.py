"""Diagnostic evidence must not masquerade as frozen release evidence."""

import hashlib
import importlib.util
from pathlib import Path
import platform
import subprocess
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("audition_cli", ROOT / "scripts/audition-melato.py")
CLI = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CLI)


class DiagnosticReceiptTests(unittest.TestCase):
    def receipt(self, status="", git_error=False):
        with tempfile.TemporaryDirectory() as tmp:
            protocol = Path(tmp) / "protocol.json"
            manifest = Path(tmp) / "manifest.json"
            protocol.write_bytes(b'{"scale":4}')
            manifest.write_bytes(b'{"split_frozen":false}')
            results = [subprocess.CompletedProcess([], 0, "a" * 40 + "\n"),
                       subprocess.CompletedProcess([], 0, status)]
            with patch.object(CLI.subprocess, "run", side_effect=OSError("no git") if git_error else results):
                return CLI._diagnostic_receipt(protocol, manifest)

    def test_records_actual_hashes_and_runtime_but_no_corpus_lock(self):
        receipt = self.receipt()
        self.assertEqual(receipt["code_sha"], "a" * 40)
        self.assertEqual(receipt["source_manifest_sha256"], hashlib.sha256(b'{"split_frozen":false}').hexdigest())
        self.assertEqual(receipt["calibration_recipe_sha256"], hashlib.sha256(b'{"scale":4}').hexdigest())
        self.assertEqual(receipt["runtime_versions"]["python"], platform.python_version())
        self.assertIsNone(receipt["corpus_lock_sha256"])
        self.assertEqual(receipt["model_weight_hashes"], {})

    def test_dirty_checkout_does_not_claim_exact_committed_code(self):
        receipt = self.receipt(" M scripts/audition-melato.py\n")
        self.assertIsNone(receipt["code_sha"])
        self.assertTrue(receipt["working_tree_dirty"])
        self.assertEqual(receipt["code_base_sha"], "a" * 40)

    def test_archive_without_git_keeps_code_identity_unknown(self):
        receipt = self.receipt(git_error=True)
        self.assertIsNone(receipt["code_sha"])
        self.assertIsNone(receipt["working_tree_dirty"])
        self.assertEqual(len(receipt["script_sha256"]), 64)

    def test_diagnostic_is_incomplete_and_recipe_is_not_frozen(self):
        result = CLI._build_acceptance_payload({"cases": []}, {}, self.receipt())
        self.assertFalse(result["reproducibility_receipt"]["complete"])
        self.assertIn("corpus_lock_sha256", result["reproducibility_receipt"]["missing_fields"])
        self.assertFalse(result["calibration"]["recipe_frozen"])
        self.assertNotEqual(result["overall_status"], "accepted")


if __name__ == "__main__":
    unittest.main()
