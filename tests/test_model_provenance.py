"""Regression tests for F05-B (MEL-75) candidate model provenance and usage terms."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from fidelis.studio.capabilities import inventory  # noqa: E402
from fidelis.studio.provenance import (  # noqa: E402
    ProvenanceError,
    audit_model_provenance,
    sha256_file,
    validate_provenance_catalog,
)


class ModelProvenanceTests(unittest.TestCase):
    """Verify real revisions/hashes vs unpinned/missing weights and separate license terms."""

    def test_committed_catalog_cross_checks_tsv_and_never_certifies_missing_or_restricted(self) -> None:
        catalog_path = REPO_ROOT / "config" / "model-provenance-v1.json"
        tsv_path = REPO_ROOT / "config" / "photo-candidates.tsv"
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))

        summary = validate_provenance_catalog(catalog, tsv_path=tsv_path)
        self.assertTrue(summary["tsv_cross_checked"])
        self.assertEqual(summary["by_provenance_status"]["pinned_sha256"], 3)
        self.assertGreaterEqual(summary["model_count"], 10)

        by_id = {m["model_id"]: m for m in catalog["models"]}
        self.assertTrue(by_id["RealeSR-general-v3"]["terms"]["production_terms_cleared"])
        for restricted in (
            "RealSR-DF2K",
            "ESRGAN-Remacri",
            "4x-UltraSharp",
            "yunet-face-detection-2023mar",
            "codeformer-onnx",
            "clarity-upscaler-ref",
            "flux-1-dev",
            "segformer-b2-clothes",
        ):
            self.assertFalse(by_id[restricted]["terms"]["production_terms_cleared"], restricted)
            self.assertFalse(by_id[restricted]["quality_certified"], restricted)

        self.assertEqual(by_id["clarity-upscaler-ref"]["terms"]["commercial_status"], "copyleft_agpl_restricted")
        self.assertEqual(by_id["flux-1-dev"]["terms"]["commercial_status"], "non_commercial_restricted")
        self.assertEqual(by_id["codeformer-onnx"]["terms"]["commercial_status"], "non_commercial_restricted")

    def test_empty_home_reports_missing_without_claiming_installed_or_certified(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            report = audit_model_provenance(REPO_ROOT, app_home=Path(home))
        for m in report["models"]:
            self.assertFalse(m["installed"], m["model_id"])
            self.assertFalse(m["quality_certified"], m["model_id"])
            self.assertIn(m["integrity"], ("missing", "not_acquired"))

    def test_tampered_pinned_bytes_and_unpinned_local_bytes_fail_safely(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            root = Path(home)
            pinned_dir = root / "runtime" / "models-RealeSR-general-v3"
            pinned_dir.mkdir(parents=True)
            (pinned_dir / "x4.param").write_bytes(b"corrupted param")
            (pinned_dir / "x4.bin").write_bytes(b"corrupted bin")

            portrait_dir = root / "models" / "portrait"
            portrait_dir.mkdir(parents=True)
            (portrait_dir / "yunet.onnx").write_bytes(b"fake-onnx")

            report = audit_model_provenance(REPO_ROOT, app_home=root)
            by_id = {m["model_id"]: m for m in report["models"]}

            # Tampered pinned candidate fails integrity cleanly
            self.assertEqual(by_id["RealeSR-general-v3"]["integrity"], "mismatch")
            # Unpinned ONNX bytes present on disk must report unpinned_local, never "matched"
            self.assertEqual(by_id["yunet-face-detection-2023mar"]["integrity"], "unpinned_local")
            self.assertFalse(by_id["yunet-face-detection-2023mar"]["production_terms_cleared"])
            self.assertEqual(
                by_id["yunet-face-detection-2023mar"]["files"]["yunet.onnx"]["actual_sha256"],
                sha256_file(portrait_dir / "yunet.onnx"),
            )

    def test_validator_rejects_bad_hashes_unclear_terms_clearance_and_tsv_drift(self) -> None:
        catalog_path = REPO_ROOT / "config" / "model-provenance-v1.json"
        base = json.loads(catalog_path.read_text(encoding="utf-8"))

        # 1. Invalid pinned SHA-256 rejected
        bad_hash = copy.deepcopy(base)
        bad_hash["models"][0]["weights"]["x4.bin"] = "not-a-sha"
        with self.assertRaises(ProvenanceError):
            validate_provenance_catalog(bad_hash)

        # 2. Cannot mark restricted license as production_terms_cleared
        bad_terms = copy.deepcopy(base)
        for m in bad_terms["models"]:
            if m["model_id"] == "flux-1-dev":
                m["terms"]["production_terms_cleared"] = True
        with self.assertRaises(ProvenanceError):
            validate_provenance_catalog(bad_terms)

        # 3. Cannot mark unpinned model as production_terms_cleared even if MIT
        bad_unpinned = copy.deepcopy(base)
        for m in bad_unpinned["models"]:
            if m["model_id"] == "yunet-face-detection-2023mar":
                m["terms"]["production_terms_cleared"] = True
        with self.assertRaises(ProvenanceError):
            validate_provenance_catalog(bad_unpinned)

        # 4. Cannot set quality_certified=True in static declaration
        bad_cert = copy.deepcopy(base)
        bad_cert["models"][0]["quality_certified"] = True
        with self.assertRaises(ProvenanceError):
            validate_provenance_catalog(bad_cert)

        # 5. TSV drift detected
        with tempfile.TemporaryDirectory() as td:
            tsv = Path(td) / "candidates.tsv"
            tsv.write_text(
                "# header\n"
                "RealeSR-general-v3\tmobile-general\t0fe68041370150c7695816e229dc982bfc06ed58\tmodels-RealeSR-general-v3\t"
                + ("a" * 64)
                + "\t"
                + ("b" * 64)
                + "\tnote\n",
                encoding="utf-8",
            )
            with self.assertRaises(ProvenanceError):
                validate_provenance_catalog(base, tsv_path=tsv)

    def test_cli_and_capabilities_inventory_include_provenance_report(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            proc = subprocess.run(
                [sys.executable, str(REPO_ROOT / "scripts" / "audit-model-provenance.py"), "--app-home", home, "--json"],
                capture_output=True,
                text=True,
                check=True,
            )
            cli_data = json.loads(proc.stdout)
            self.assertEqual(cli_data["catalog_summary"]["by_provenance_status"]["pinned_sha256"], 3)

            inv = inventory(REPO_ROOT, home)
            self.assertIn("candidates", inv)
            self.assertIn("model_provenance", inv)
            self.assertEqual(inv["model_provenance"]["catalog_summary"]["model_count"], cli_data["catalog_summary"]["model_count"])


if __name__ == "__main__":
    unittest.main()
