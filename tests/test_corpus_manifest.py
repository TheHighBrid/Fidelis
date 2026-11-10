"""Regression tests for F12-A (MEL-79) 60-case corpus rights and ROI manifest."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from fidelis.eval.corpus_manifest import (  # noqa: E402
    ManifestValidationError,
    build_template_manifest,
    load_corpus_manifest,
    sha256_file,
    validate_corpus_manifest,
)


class CorpusManifestTests(unittest.TestCase):
    """Verify frozen 60-case inventory, honest availability, rights, ROI, and hash gates."""

    def test_committed_manifest_freezes_60_slots_and_separates_regression_assets(self) -> None:
        manifest_path = REPO_ROOT / "experiments" / "corpus_manifest.json"
        data, summary = load_corpus_manifest(
            manifest_path,
            repo_root=REPO_ROOT,
            verify_files=True,
        )
        self.assertTrue(summary["split_frozen"])
        self.assertEqual(summary["total_slots"], 60)
        self.assertEqual(summary["available_cases"], 0)
        self.assertEqual(summary["missing_cases"], 60)
        self.assertEqual(summary["by_split"]["calibration"]["total"], 30)
        self.assertEqual(summary["by_split"]["held_out"]["total"], 30)
        for cat_counts in summary["by_category"].values():
            self.assertEqual(cat_counts["total"], 12)
            self.assertEqual(cat_counts["calibration"], 6)
            self.assertEqual(cat_counts["held_out"], 6)
        self.assertEqual(summary["regression_assets_count"], 8)
        self.assertTrue(summary["regression_assets_verified"])
        for reg in data["regression_assets"]:
            self.assertFalse(reg["counts_toward_60_case_corpus"])
            self.assertFalse(reg["rights_cleared"])

    def test_available_cleared_case_with_real_png_and_rois_passes(self) -> None:
        manifest = build_template_manifest()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            img_path = root / "corpus" / "portrait_sample.png"
            img_path.parent.mkdir(parents=True, exist_ok=True)
            Image.new("RGB", (64, 48), color=(180, 140, 120)).save(img_path)

            case = manifest["cases"][0]
            case["availability"] = "available"
            case["rights"] = {
                "cleared": True,
                "permission_basis": "written_model_release",
                "license_id": "MEL-TEST-001",
                "model_release_required": True,
                "model_release_verified": True,
                "notes": "Test fixture cleared consent",
            }
            case["source"] = {
                "relative_path": "corpus/portrait_sample.png",
                "sha256": sha256_file(img_path),
                "width": 64,
                "height": 48,
                "color_space": "sRGB",
                "bit_depth": 8,
                "has_alpha": False,
            }
            case["critical_rois"][0]["bbox_norm"] = [0.25, 0.2, 0.75, 0.6]

            summary = validate_corpus_manifest(manifest, repo_root=root, verify_files=True)
            self.assertEqual(summary["available_cases"], 1)
            self.assertEqual(summary["missing_cases"], 59)

    def test_fail_closed_on_missing_rights_release_or_malformed_rois(self) -> None:
        base = build_template_manifest()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            img_path = root / "sample.png"
            Image.new("RGB", (32, 32), color=(100, 120, 140)).save(img_path)
            sha = sha256_file(img_path)

            def make_available():
                m = copy.deepcopy(base)
                c = m["cases"][0]
                c["availability"] = "available"
                c["rights"] = {
                    "cleared": True,
                    "permission_basis": "direct_commission",
                    "license_id": "LIC-1",
                    "model_release_required": True,
                    "model_release_verified": True,
                }
                c["source"] = {"relative_path": "sample.png", "sha256": sha, "width": 32, "height": 32}
                c["critical_rois"][0]["bbox_norm"] = [0.1, 0.1, 0.9, 0.9]
                return m

            # 1. Available without cleared=True
            m1 = make_available()
            m1["cases"][0]["rights"]["cleared"] = False
            with self.assertRaises(ManifestValidationError):
                validate_corpus_manifest(m1, repo_root=root, verify_files=True)

            # 2. Missing model release verification
            m2 = make_available()
            m2["cases"][0]["rights"]["model_release_verified"] = False
            with self.assertRaises(ManifestValidationError):
                validate_corpus_manifest(m2, repo_root=root, verify_files=True)

            # 3. Missing case claiming cleared=True or fabricated sha256
            m3 = copy.deepcopy(base)
            m3["cases"][0]["rights"]["cleared"] = True
            with self.assertRaises(ManifestValidationError):
                validate_corpus_manifest(m3)

            m4 = copy.deepcopy(base)
            m4["cases"][0]["source"]["sha256"] = sha
            with self.assertRaises(ManifestValidationError):
                validate_corpus_manifest(m4)

            # 4. Available case with missing or out-of-range ROI bbox
            m5 = make_available()
            m5["cases"][0]["critical_rois"][0]["bbox_norm"] = None
            with self.assertRaises(ManifestValidationError):
                validate_corpus_manifest(m5, repo_root=root, verify_files=True)

            m6 = make_available()
            m6["cases"][0]["critical_rois"][0]["bbox_norm"] = [0.6, 0.1, 0.5, 0.9]
            with self.assertRaises(ManifestValidationError):
                validate_corpus_manifest(m6, repo_root=root, verify_files=True)

    def test_fail_closed_on_hash_dim_mismatch_traversal_and_split_leakage(self) -> None:
        base = build_template_manifest()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            img_path = root / "sample.png"
            Image.new("RGB", (32, 32), color=(90, 90, 90)).save(img_path)
            sha = sha256_file(img_path)

            def prepare():
                m = copy.deepcopy(base)
                c = m["cases"][0]
                c["availability"] = "available"
                c["rights"] = {
                    "cleared": True,
                    "permission_basis": "licensed",
                    "license_id": "LIC-2",
                    "model_release_required": False,
                    "model_release_verified": False,
                }
                c["source"] = {"relative_path": "sample.png", "sha256": sha, "width": 32, "height": 32}
                c["critical_rois"][0]["bbox_norm"] = [0.2, 0.2, 0.8, 0.8]
                return m

            # Bad hash on disk
            bad_sha = prepare()
            bad_sha["cases"][0]["source"]["sha256"] = "0" * 64
            with self.assertRaises(ManifestValidationError):
                validate_corpus_manifest(bad_sha, repo_root=root, verify_files=True)

            # Dimension mismatch on disk
            bad_dim = prepare()
            bad_dim["cases"][0]["source"]["width"] = 64
            with self.assertRaises(ManifestValidationError):
                validate_corpus_manifest(bad_dim, repo_root=root, verify_files=True)

            # Path traversal rejected
            bad_path = prepare()
            bad_path["cases"][0]["source"]["relative_path"] = "../outside.png"
            with self.assertRaises(ManifestValidationError):
                validate_corpus_manifest(bad_path, repo_root=root, verify_files=True)

            # Cross-split SHA leakage between calibration (index 0) and held_out (index 6)
            leak = prepare()
            held = leak["cases"][6]
            self.assertEqual(held["split"], "held_out")
            held["availability"] = "available"
            held["rights"] = dict(leak["cases"][0]["rights"])
            held["source"] = dict(leak["cases"][0]["source"])
            held["critical_rois"][0]["bbox_norm"] = [0.2, 0.2, 0.8, 0.8]
            with self.assertRaises(ManifestValidationError):
                validate_corpus_manifest(leak, repo_root=root, verify_files=False)

    def test_fail_closed_on_split_freeze_and_category_counts(self) -> None:
        m1 = build_template_manifest()
        m1["split_frozen"] = False
        with self.assertRaises(ManifestValidationError):
            validate_corpus_manifest(m1)

        m2 = build_template_manifest()
        m2["cases"].pop()
        with self.assertRaises(ManifestValidationError):
            validate_corpus_manifest(m2)

        m3 = build_template_manifest()
        m3["cases"][6]["split"] = "calibration"  # breaks 6/6 portrait split
        with self.assertRaises(ManifestValidationError):
            validate_corpus_manifest(m3)

    def test_cli_validator_succeeds_on_committed_manifest(self) -> None:
        proc = subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "validate-corpus-manifest.py"), "--verify-files", "--json"],
            capture_output=True,
            text=True,
            check=True,
        )
        summary = json.loads(proc.stdout)
        self.assertEqual(summary["total_slots"], 60)
        self.assertEqual(summary["available_cases"], 0)
        self.assertEqual(summary["regression_assets_count"], 8)
        self.assertTrue(summary["regression_assets_verified"])


if __name__ == "__main__":
    unittest.main()
