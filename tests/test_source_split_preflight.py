"""Regression coverage for source aliases crossing frozen split boundaries."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fidelis.eval.source_split_preflight import check_source_split_isolation


ROOT = Path(__file__).resolve().parents[1]
SOURCE_SHA = "bd1249a6e7ea02a231d199035a578d1b391815f8e57389aec2de1c28ebacb91b"


class SourceSplitPreflightTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)

    def manifest(self, name, records, key="cases"):
        path = self.directory / name
        path.write_text(json.dumps({"schema_version": 1, key: records}), encoding="utf-8")
        return path

    def case(self, identity="portrait", split="held_out", sha=SOURCE_SHA):
        return {"case_id": identity, "split": split, "source": {"sha256": sha}}

    def test_real_manifest_alias_conflict_and_no_mutation(self):
        frozen = self.manifest("frozen.json", [self.case("por_held_high_iso_backstage")])
        approved = self.manifest("approved.json", [{"asset_id": "mel_014", "split": "calibration",
                                                   "source": {"sha256": SOURCE_SHA}}], "assets")
        before = [path.read_bytes() for path in (frozen, approved)]
        report = check_source_split_isolation([frozen, approved])
        self.assertFalse(report["passed"])
        self.assertEqual(report["summary"]["conflict_count"], 1)
        self.assertEqual({x["id"] for x in report["conflicts"][0]["aliases"]},
                         {"por_held_high_iso_backstage", "mel_014"})
        self.assertEqual(before, [path.read_bytes() for path in (frozen, approved)])

    def test_same_split_aliases_pass_and_uppercase_cannot_hide_identity(self):
        path = self.manifest("same.json", [self.case(), self.case("other", sha=SOURCE_SHA.upper())])
        report = check_source_split_isolation([path])
        self.assertTrue(report["passed"])
        self.assertEqual(len(report["shared_sources"]), 1)
        self.assertEqual(report["summary"]["unique_source_hashes"], 1)

    def test_missing_hashes_are_unknown_and_not_false_overlaps(self):
        path = self.manifest("missing.json", [self.case(sha=None), self.case("unknown", "calibration", "")])
        report = check_source_split_isolation([path])
        self.assertFalse(report["passed"])
        self.assertEqual(report["status"], "incomplete")
        self.assertEqual(report["summary"]["unknown_hash_count"], 2)
        self.assertEqual(report["shared_sources"], [])

    def test_malformed_nonempty_hashes_fail_closed(self):
        for sha in ("local", "g" * 64, "a" * 63, " " * 64, 12, [], False):
            with self.subTest(sha=sha):
                path = self.manifest("invalid.json", [self.case(sha=sha)])
                report = check_source_split_isolation([path])
                self.assertFalse(report["passed"])
                self.assertEqual(report["summary"]["error_count"], 1)

    def test_diagnostic_alias_and_disagreeing_hash_fields(self):
        row = {"id": "mel_014_calibration", "split": "calibration", "source_sha256": SOURCE_SHA}
        diagnostic = self.manifest("diagnostic.json", [row])
        frozen = self.manifest("frozen.json", [self.case()])
        self.assertFalse(check_source_split_isolation([frozen, diagnostic])["passed"])
        row["source"] = {"sha256": "a" * 64}
        diagnostic = self.manifest("diagnostic.json", [row])
        self.assertIn("disagree", check_source_split_isolation([diagnostic])["errors"][0]["error"])

    def test_invalid_structure_and_unreadable_inputs_fail_closed(self):
        path = self.directory / "bad.json"
        documents = [[], {}, {"schema_version": 1, "cases": [], "assets": []},
                     {"schema_version": 1, "cases": [self.case(split="unknown")]},
                     {"schema_version": 1, "cases": [self.case(), self.case()]},
                     {"schema_version": 1, "cases": [None]}]
        for document in documents:
            path.write_text(json.dumps(document))
            self.assertFalse(check_source_split_isolation([path])["passed"])
        path.write_text("{broken")
        self.assertFalse(check_source_split_isolation([path])["passed"])
        self.assertFalse(check_source_split_isolation([self.directory / "absent"])["passed"])
        self.assertFalse(check_source_split_isolation([])["passed"])

    def test_only_explicit_manifest_is_read(self):
        row = self.case()
        row["source"]["relative_path"] = "/private/do-not-open.jpg"
        path = self.manifest("explicit.json", [row])
        original = Path.read_bytes
        reads = []

        def read_bytes(target):
            reads.append(target)
            if target != path.resolve():
                raise AssertionError("Attempted a non-manifest read")
            return original(target)

        with patch.object(Path, "read_bytes", read_bytes):
            self.assertTrue(check_source_split_isolation([path])["passed"])
        self.assertEqual(reads, [path.resolve()])

    def test_cli_json_and_exit_status(self):
        first = self.manifest("first.json", [self.case()])
        second = self.manifest("second.json", [self.case("calibration_alias", "calibration")])
        command = [sys.executable, str(ROOT / "scripts/check-source-split-isolation.py"),
                   "--manifest", str(first)]
        clear = subprocess.run(command, capture_output=True, text=True, check=False)
        self.assertEqual(clear.returncode, 0, clear.stderr)
        self.assertTrue(json.loads(clear.stdout)["passed"])
        conflict = subprocess.run(command + ["--manifest", str(second)], capture_output=True,
                                  text=True, check=False)
        self.assertEqual(conflict.returncode, 1, conflict.stderr)
        self.assertEqual(json.loads(conflict.stdout)["summary"]["conflict_count"], 1)


if __name__ == "__main__":
    unittest.main()
