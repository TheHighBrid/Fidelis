"""Regression tests for F12-A (MEL-79) 60-case corpus rights and ROI manifest."""

from __future__ import annotations

import copy
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from fidelis.eval.corpus_manifest import (
    ManifestValidationError,
    assert_restoration_ground_truth_allowed,
    build_template_manifest,
    load_corpus_manifest,
    load_melato_corpus_manifest,
    sha256_file,
    validate_corpus_manifest,
    validate_melato_corpus_manifest,
)


class CorpusManifestTests(unittest.TestCase):
    """Verify frozen 60-case inventory, honest availability, rights, ROI, and hash gates."""

    def test_committed_manifest_freezes_60_slots_and_separates_regression_assets(self) -> None:
        manifest_path = REPO_ROOT / "experiments" / "corpus_manifest.json"
        # CI path: verify in-repo regression assets; skip Melato byte checks without --master-root.
        data, summary = load_corpus_manifest(
            manifest_path,
            repo_root=REPO_ROOT,
            verify_files=True,
            master_root=None,
        )
        self.assertTrue(summary["split_frozen"])
        self.assertEqual(summary["total_slots"], 60)
        self.assertGreaterEqual(summary["available_cases"], 0)
        self.assertEqual(summary["available_cases"] + summary["missing_cases"] + summary["excluded_cases"], 60)
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
        for case in data["cases"]:
            if case["availability"] == "available":
                self.assertEqual(case["source"].get("storage"), "off_repo")
                self.assertIsNone(case["source"].get("relative_path"))
                self.assertTrue(case["rights"]["cleared"])
                self.assertNotEqual(case.get("synthetic"), True)

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
        # Exercise the same validation path the CLI wraps (no subprocess).
        _, summary = load_corpus_manifest(
            REPO_ROOT / "experiments" / "corpus_manifest.json",
            repo_root=REPO_ROOT,
            verify_files=True,
            master_root=None,
        )
        self.assertEqual(summary["total_slots"], 60)
        self.assertEqual(summary["available_cases"] + summary["missing_cases"], 60)
        self.assertEqual(summary["regression_assets_count"], 8)
        self.assertTrue(summary["regression_assets_verified"])
        self.assertGreaterEqual(summary.get("off_repo_available_cases", 0), 0)

    def test_melato_companion_manifest_inventories_97_off_repo_assets(self) -> None:
        melato_path = REPO_ROOT / "experiments" / "melato_corpus_manifest.json"
        self.assertTrue(melato_path.is_file())
        data, summary = load_melato_corpus_manifest(melato_path, verify_files=False)
        self.assertEqual(summary["total_assets"], 97)
        self.assertEqual(summary["ground_truth_eligible"] + summary["non_ground_truth"], 97)
        self.assertGreater(summary["non_ground_truth"], 0)
        for asset in data["assets"]:
            self.assertEqual(asset["storage"], "off_repo")
            self.assertIsNone(asset["source"].get("relative_path"))
            if asset["synthetic"]:
                self.assertFalse(asset["ground_truth_eligible"])
                self.assertEqual(asset["set"], "non_ground_truth")
                with self.assertRaises(ManifestValidationError):
                    assert_restoration_ground_truth_allowed(asset)

    def test_off_repo_available_case_passes_without_in_repo_path_or_bbox(self) -> None:
        manifest = build_template_manifest()
        case = manifest["cases"][0]
        case["availability"] = "available"
        case["ground_truth_eligible"] = True
        case["synthetic"] = False
        case["rights"] = {
            "cleared": True,
            "permission_basis": "owner_melato_vouched_2026-11-19",
            "license_id": "MELATO-OWNER-2026-11-19",
            "model_release_required": True,
            "model_release_verified": True,
            "notes": "off-repo test",
        }
        case["source"] = {
            "storage": "off_repo",
            "filename": "portrait_sample.png",
            "relative_path": None,
            "sha256": "a" * 64,
            "width": 64,
            "height": 48,
            "color_space": "sRGB",
            "bit_depth": 8,
            "has_alpha": False,
            "off_repo_root_env": "FIDELIS_MELATO_MASTER_ROOT",
        }
        # bbox remains null — allowed for off_repo
        summary = validate_corpus_manifest(manifest, repo_root=REPO_ROOT, verify_files=True, master_root=None)
        self.assertEqual(summary["available_cases"], 1)
        self.assertEqual(summary["off_repo_available_cases"], 1)
        self.assertEqual(summary["files_skipped_no_master"], 1)

    def test_off_repo_verify_with_master_root(self) -> None:
        manifest = build_template_manifest()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            img_path = root / "portrait_sample.png"
            Image.new("RGB", (64, 48), color=(180, 140, 120)).save(img_path)
            case = manifest["cases"][0]
            case["availability"] = "available"
            case["ground_truth_eligible"] = True
            case["synthetic"] = False
            case["rights"] = {
                "cleared": True,
                "permission_basis": "owner_melato_vouched_2026-11-19",
                "license_id": "MELATO-OWNER-2026-11-19",
                "model_release_required": True,
                "model_release_verified": True,
                "notes": "off-repo test",
            }
            case["source"] = {
                "storage": "off_repo",
                "filename": "portrait_sample.png",
                "relative_path": None,
                "sha256": sha256_file(img_path),
                "width": 64,
                "height": 48,
            }
            summary = validate_corpus_manifest(
                manifest, repo_root=REPO_ROOT, verify_files=True, master_root=root
            )
            self.assertEqual(summary["files_verified"], 1)

    def test_available_cases_reject_non_ground_truth_regardless_of_storage(self) -> None:
        for flags in ({"synthetic": True}, {"ground_truth_eligible": False},
                      {"set": "non_ground_truth"}):
            with self.subTest(flags=flags):
                manifest = build_template_manifest()
                case = manifest["cases"][0]
                case.update(flags, availability="available")
                case["rights"].update(cleared=True, permission_basis="test", license_id="TEST",
                                      model_release_verified=True)
                case["source"] = {"relative_path": "sample.png", "sha256": "a" * 64,
                                  "width": 64, "height": 48}
                case["critical_rois"][0]["bbox_norm"] = [0.1, 0.1, 0.9, 0.9]
                with self.assertRaises(ManifestValidationError):
                    validate_corpus_manifest(manifest)

    def test_off_repo_filenames_cannot_escape_master_root(self) -> None:
        frozen, _ = load_corpus_manifest(REPO_ROOT / "experiments" / "corpus_manifest.json")
        melato, _ = load_melato_corpus_manifest(REPO_ROOT / "experiments" / "melato_corpus_manifest.json")
        case = next(c for c in frozen["cases"] if c["availability"] == "available")
        asset = melato["assets"][0]
        for filename in ("../outside.png", "/tmp/outside.png", "..\\outside.png",
                         "C:\\outside.png", "nested/sample.png", ".", "..", "bad\x00.png"):
            with self.subTest(filename=filename):
                case["source"]["filename"] = filename
                asset["source"]["filename"] = filename
                with self.assertRaises(ManifestValidationError):
                    validate_corpus_manifest(frozen)
                with self.assertRaises(ManifestValidationError):
                    validate_melato_corpus_manifest(melato)

    def test_off_repo_symlink_cannot_escape_master_root(self) -> None:
        frozen, _ = load_corpus_manifest(REPO_ROOT / "experiments" / "corpus_manifest.json")
        melato, _ = load_melato_corpus_manifest(REPO_ROOT / "experiments" / "melato_corpus_manifest.json")
        case = next(c for c in frozen["cases"] if c["availability"] == "available")
        asset = melato["assets"][0]
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "masters"
            root.mkdir()
            outside = Path(td) / "outside.png"
            Image.new("RGB", (64, 48)).save(outside)
            (root / "escape.png").symlink_to(outside)
            for entry in (case, asset):
                entry["source"].update(filename="escape.png", sha256=sha256_file(outside),
                                       width=64, height=48)
            with self.assertRaisesRegex(ManifestValidationError, "escapes"):
                validate_corpus_manifest(frozen, master_root=root, verify_files=True)
            with self.assertRaisesRegex(ManifestValidationError, "escapes"):
                validate_melato_corpus_manifest(melato, master_root=root, verify_files=True)

    def test_melato_summary_matches_assets_and_local_audited_rois_populated(self) -> None:
        frozen, _ = load_corpus_manifest(REPO_ROOT / "experiments" / "corpus_manifest.json")
        melato, summary = load_melato_corpus_manifest(
            REPO_ROOT / "experiments" / "melato_corpus_manifest.json"
        )
        self.assertEqual(melato["summary"]["by_category"], summary["by_category"])
        by_id = {asset["asset_id"]: asset for asset in melato["assets"]}
        self.assertEqual(by_id["mel_028"]["category"], "apparel_model")
        for aid in ("mel_010", "mel_014", "mel_028", "mel_029", "mel_038", "mel_040", "mel_056", "mel_057"):
            self.assertTrue(all(roi["bbox_norm"] is not None for roi in by_id[aid]["critical_rois"]))
        cases_by_id = {case["case_id"]: case for case in frozen["cases"]}
        for cid in ("por_held_glasses_reflection", "por_held_high_iso_backstage"):
            self.assertIsNotNone(cases_by_id[cid]["critical_rois"][0]["bbox_norm"])


if __name__ == "__main__":
    unittest.main()
