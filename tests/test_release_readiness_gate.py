"""Regression tests for offline release declaration gate."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_release_readiness.py"
spec = importlib.util.spec_from_file_location("release_gate", SCRIPT)
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


def accepted():
    return {"schema_version": "fidelis.release_candidate.v1", "merged_to_main": True,
            "quality_gate": {"overall_status": "accepted", "report_sha256": "a" * 64},
            "operational_gate": {"live_worker_verified": True,
                                 "device_budgets_measured": True,
                                 "upgrade_rollback_verified": True},
            "owner_release_signoff": {"status": "approved", "creative_owner": "reviewer",
                                      "release_owner": "maintainer", "signed_at": "2026-11-20"}}


class ReleaseGateTests(unittest.TestCase):
    def test_accepted_declarations_are_not_external_certification(self):
        result = gate.assess(accepted())
        self.assertTrue(result["ready"])
        self.assertEqual(result["evidence_level"], "manifest_declarations_only")

    def test_each_required_gate_fails_closed(self):
        cases = [("root", "merged_to_main", False),
                 ("quality_gate", "overall_status", "pending"),
                 ("quality_gate", "report_sha256", None),
                 ("operational_gate", "live_worker_verified", False),
                 ("operational_gate", "device_budgets_measured", False),
                 ("operational_gate", "upgrade_rollback_verified", False),
                 ("owner_release_signoff", "status", "pending"),
                 ("owner_release_signoff", "creative_owner", None),
                 ("owner_release_signoff", "release_owner", None),
                 ("owner_release_signoff", "signed_at", None)]
        for section, key, value in cases:
            with self.subTest(section=section, key=key):
                manifest = accepted()
                target = manifest if section == "root" else manifest[section]
                target[key] = value
                self.assertFalse(gate.assess(manifest)["ready"])

    def test_invalid_hash_and_truthy_string_rejected(self):
        manifest = accepted()
        manifest["quality_gate"]["report_sha256"] = "z" * 64
        manifest["merged_to_main"] = "true"
        self.assertIn("quality_accepted", gate.assess(manifest)["unmet"])
        self.assertIn("merged_to_main", gate.assess(manifest)["unmet"])

    def test_missing_sections_rejected(self):
        for value in ({}, [], {"schema_version": "other"},
                      {"schema_version": "fidelis.release_candidate.v1", "quality_gate": []}):
            with self.assertRaises(gate.ManifestError):
                gate.assess(value)

    def test_cli_exit_codes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "release.json"
            path.write_text(json.dumps(accepted()))
            self.assertEqual(subprocess.run([sys.executable, str(SCRIPT), str(path)],
                                            capture_output=True).returncode, 0)
            pending = accepted()
            pending["merged_to_main"] = False
            path.write_text(json.dumps(pending))
            self.assertEqual(subprocess.run([sys.executable, str(SCRIPT), str(path)],
                                            capture_output=True).returncode, 1)
            path.write_text("{")
            self.assertEqual(subprocess.run([sys.executable, str(SCRIPT), str(path)],
                                            capture_output=True).returncode, 2)


if __name__ == "__main__":
    unittest.main()
