"""Unit tests for fidelis.studio.audition (F8) and CLI/Batch integration."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

from fidelis.engine import DimensionMismatchError, create_restoration_runner
from fidelis.studio.audition import (
    classify_audition_outcome,
    generate_side_by_side_crops,
    load_audition_cases_from_manifest,
    run_model_vs_bicubic_audition,
)
from fidelis.studio.batch import BatchRunner, make_audition_worker


REPO_ROOT = Path(__file__).resolve().parents[1]


def _make_source_and_candidate(h: int = 24, w: int = 24) -> tuple[np.ndarray, np.ndarray]:
    yy, xx = np.mgrid[0:h, 0:w]
    base = (128 + 40 * np.sin(xx * 0.7) * np.cos(yy * 0.7)).astype(np.uint8)
    src = np.stack([base, base, base], axis=-1)
    bic = np.asarray(Image.fromarray(src).resize((w * 4, h * 4), Image.Resampling.BICUBIC), dtype=np.uint8)
    # Add fine weave-like micro-texture on 4x grid
    y4, x4 = np.mgrid[0 : h * 4, 0 : w * 4]
    delta = (10 * np.sin(x4 * 1.1) * np.cos(y4 * 1.1)).astype(np.int16)
    cand = np.clip(bic.astype(np.int16) + delta[..., None], 0, 255).astype(np.uint8)
    return src, cand


class ModelAuditionTests(unittest.TestCase):
    def test_final_drift_failure_cannot_pass_detail_gates(self) -> None:
        passed_detail = {
            "status": "measured", "interior_texture_passed": True,
            "oversharpen_restraint_passed": True, "fabric_weave_passed": True,
            "hardware_seam_passed": True, "all_detail_gates_passed": True,
        }
        source = np.full((8, 8, 3), 128, dtype=np.uint8)
        candidate = np.full((32, 32, 3), 128, dtype=np.uint8)
        for verdict, mismatches, reason in (
            ("FAIL", 0, "geometric_drift"),
            ("PASS", 1, "protected_pixel_mismatch"),
        ):
            for batch in (False, True):
                with self.subTest(verdict=verdict, batch=batch), tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    src_path, candidate_path = root / "source.png", root / "candidate.png"
                    Image.fromarray(source).save(src_path)
                    Image.fromarray(candidate).save(candidate_path)
                    with patch("fidelis.engine.restoration_runner.screen_internal_drift", return_value={
                        "overall_verdict": verdict, "locked_pixel_mismatches": mismatches,
                    }), patch("fidelis.studio.audition.BenchmarkSuite.evaluate_4x_detail", return_value=passed_detail.copy()):
                        if batch:
                            runner = create_restoration_runner("imported", file_map={"case": candidate_path})
                            report = run_model_vs_bicubic_audition(
                                [{"id": "case", "source_path": str(src_path), "rois": []}],
                                runner, output_dir=root / "out", generate_html=False,
                            )
                        else:
                            report = run_model_vs_bicubic_audition(
                                source_rgb=source, candidate_4x_rgb=candidate,
                                rois=[], output_dir=root / "out", generate_html=False,
                            )
                    outcome = report["cases"][0]["outcome"]
                    self.assertFalse(report["summary"]["all_passed"])
                    self.assertEqual(outcome["outcome"], "FAIL_FAITHFULNESS")
                    self.assertIn(reason, outcome["failure_reasons"])

    def test_classify_audition_outcome_all_states(self) -> None:
        p = classify_audition_outcome(
            {
                "status": "measured",
                "interior_texture_passed": True,
                "oversharpen_restraint_passed": True,
                "fabric_weave_passed": True,
                "hardware_seam_passed": True,
                "all_detail_gates_passed": True,
            }
        )
        self.assertEqual(p["outcome"], "PASS_MATERIAL_DETAIL")
        self.assertTrue(p["passed"])
        self.assertEqual(p["failure_reasons"], [])

        s = classify_audition_outcome(
            {
                "status": "measured",
                "interior_texture_passed": False,
                "oversharpen_restraint_passed": True,
                "fabric_weave_passed": True,
                "hardware_seam_passed": True,
                "all_detail_gates_passed": False,
                "interior_texture": {"reason": "texture_smoothed_below_bicubic"},
            }
        )
        self.assertEqual(s["outcome"], "FAIL_SMOOTHING_REGRESSION")
        self.assertFalse(s["passed"])
        self.assertIn("texture_smoothed_below_bicubic", s["failure_reasons"])

        sh = classify_audition_outcome(
            {
                "status": "measured",
                "interior_texture_passed": True,
                "oversharpen_restraint_passed": False,
                "fabric_weave_passed": True,
                "hardware_seam_passed": True,
                "all_detail_gates_passed": False,
            }
        )
        self.assertEqual(sh["outcome"], "FAIL_SHARPENING_ONLY")
        self.assertFalse(sh["passed"])

        ff = classify_audition_outcome(
            {
                "status": "measured",
                "interior_texture_passed": True,
                "oversharpen_restraint_passed": True,
                "fabric_weave_passed": False,
                "hardware_seam_passed": True,
                "all_detail_gates_passed": False,
            }
        )
        self.assertEqual(ff["outcome"], "FAIL_FAITHFULNESS")
        self.assertFalse(ff["passed"])

    def test_generate_side_by_side_crops_exact_dimensions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cand = np.zeros((64, 64, 3), dtype=np.uint8)
            bic = np.full((64, 64, 3), 255, dtype=np.uint8)
            rois = [{"id": "crema", "kind": "crema", "policy": "texture_allowed", "rect": [8, 8, 20, 16]}]
            crops = generate_side_by_side_crops(
                cand, bic, rois=rois, output_dir=tmp, case_id="c1", roi_space="target"
            )
            self.assertEqual(len(crops), 4)
            by_key = {(c["region"], c["zoom"]): c for c in crops}
            self.assertEqual((by_key[("full_frame", 1)]["width"], by_key[("full_frame", 1)]["height"]), (64, 64))
            self.assertEqual((by_key[("full_frame", 2)]["width"], by_key[("full_frame", 2)]["height"]), (128, 128))
            self.assertEqual((by_key[("crema", 1)]["width"], by_key[("crema", 1)]["height"]), (20, 16))
            self.assertEqual((by_key[("crema", 2)]["width"], by_key[("crema", 2)]["height"]), (40, 32))
            for c in crops:
                for role, path_key in (("candidate", "candidate_path"), ("bicubic", "bicubic_path")):
                    with Image.open(c[path_key]) as im:
                        self.assertEqual((im.width, im.height), (c["width"], c["height"]))
                        self.assertEqual(im.mode, "RGB")
                self.assertNotEqual(c["candidate_path"], c["bicubic_path"])

            with self.assertRaises(DimensionMismatchError):
                generate_side_by_side_crops(
                    cand, np.zeros((32, 32, 3), dtype=np.uint8), output_dir=tmp, case_id="bad"
                )

    def test_run_model_vs_bicubic_audition_end_to_end(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src_dir = root / "src"
            imp_dir = root / "imp"
            out_dir = root / "audition_out"
            src_dir.mkdir()
            imp_dir.mkdir()

            src, cand = _make_source_and_candidate(24, 24)
            Image.fromarray(src).save(src_dir / "fabric_case.png")
            Image.fromarray(cand).save(imp_dir / "fabric_case.png")

            cases = [
                {
                    "id": "fabric_case",
                    "source_path": str(src_dir / "fabric_case.png"),
                    "rois": [
                        {"id": "weave", "kind": "fabric", "policy": "texture_allowed", "rect": [4, 4, 16, 16]},
                        {"id": "buckle", "kind": "hardware", "policy": "preserve", "rect": [0, 0, 4, 4]},
                    ],
                    "roi_space": "source",
                    "split": "held_out",
                    "category": "apparel",
                }
            ]
            runner = create_restoration_runner("imported", imported_dir=imp_dir, model_id="test_model")
            report = run_model_vs_bicubic_audition(cases, runner, output_dir=out_dir)

            self.assertEqual(report["summary"]["total_cases"], 1)
            self.assertTrue(Path(report["report_json_path"]).is_file())
            self.assertTrue(Path(report["report_html_path"]).is_file())
            self.assertTrue(Path(report["blind"]["ballot_path"]).is_file())
            self.assertTrue(Path(report["blind"]["answer_key_path"]).is_file())
            self.assertEqual(report["blind"]["pair_count"], 1)
            self.assertIn("outcome", report["cases"][0]["outcome"])
            self.assertEqual(report["cases"][0]["provenance"]["backend"], "imported")
            self.assertEqual(report["cases"][0]["provenance"]["weights_sha256"], "imported")
            self.assertEqual(len(report["cases"][0]["crops"]), 6)

    def test_cli_run_comparators_audition_and_generate_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src, cand = _make_source_and_candidate(16, 16)
            src_p = root / "sample.png"
            imp_dir = root / "imp"
            out_dir = root / "out"
            imp_dir.mkdir()
            Image.fromarray(src).save(src_p)
            Image.fromarray(cand).save(imp_dir / "sample.png")

            manifest_p = root / "cases.json"
            manifest_p.write_text(
                json.dumps(
                    {
                        "cases": [
                            {
                                "id": "sample",
                                "source_path": "sample.png",
                                "rois": [
                                    {"id": "fab", "kind": "fabric", "policy": "texture_allowed", "rect": [2, 2, 12, 12]}
                                ],
                                "roi_space": "source",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            proc = subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / "scripts" / "run-comparators.py"),
                    "audition",
                    str(manifest_p),
                    "--root",
                    str(root),
                    "--output-dir",
                    str(out_dir),
                    "--backend",
                    "imported",
                    "--imported-dir",
                    str(imp_dir),
                    "--model-id",
                    "cli_test_model",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["summary"]["total_cases"], 1)
            self.assertTrue((out_dir / "audition_report.json").is_file())

            html_out = out_dir / "regenerated.html"
            rep_proc = subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / "scripts" / "generate-audition-report.py"),
                    str(out_dir),
                    "-o",
                    str(html_out),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(rep_proc.returncode, 0, msg=rep_proc.stderr)
            self.assertTrue(html_out.is_file())
            html_text = html_out.read_text(encoding="utf-8")
            self.assertIn("MODEL_VS_BICUBIC_AUDITION", html_text)
            self.assertIn("cli_test_model", html_text)

    def test_batch_make_audition_worker_integration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src, _ = _make_source_and_candidate(16, 16)
            src_p = root / "in.png"
            out_p = root / "out.png"
            Image.fromarray(src).save(src_p)

            runner = create_restoration_runner("bicubic")
            worker = make_audition_worker(runner, eval_detail=True)
            batch = BatchRunner(root / "batch")
            try:
                batch.enqueue([{"source_path": str(src_p), "output_path": str(out_p), "recipe": {"case_id": "in"}}])
                status = batch.run(worker)
            finally:
                batch.close()
            self.assertEqual(status["counts"]["completed"], 1)
            self.assertTrue(out_p.is_file())

    def test_audition_melato_cli_realesrgan_ncnn_missing_runtime_fails_closed(self) -> None:
        import os

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = dict(os.environ)
            env["FIDELIS_HOME"] = str(root / "empty_fidelis_home")
            env.pop("FIDELIS_ENGINE", None)
            proc = subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / "scripts" / "audition-melato.py"),
                    "--smoke",
                    "--backend",
                    "realesrgan_ncnn",
                    "--detail-blend-weight",
                    "0.6",
                    "--output-dir",
                    str(root / "out"),
                ],
                cwd=str(REPO_ROOT),
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(proc.returncode, 2, msg=proc.stdout + proc.stderr)
            self.assertIn("Local NCNN runtime not installed", proc.stderr)

    def test_load_audition_cases_from_melato_and_corpus_manifests(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            master_root = root / "masters"
            master_root.mkdir()
            img_path = master_root / "mel_sample.png"
            src_arr, _ = _make_source_and_candidate(40, 20)
            Image.fromarray(src_arr).save(img_path, format="PNG")
            img_sha = hashlib.sha256(img_path.read_bytes()).hexdigest()

            melato_manifest = {
                "assets": [
                    {
                        "asset_id": "mel_sample",
                        "filename": "mel_sample.png",
                        "sha256": img_sha,
                        "category": "apparel_model",
                        "synthetic": False,
                        "ground_truth_eligible": True,
                        "critical_rois": [
                            {
                                "roi_id": "seam_lock",
                                "label": "Stripe seam",
                                "roi_type": "stitch",
                                "must_lock_base": True,
                                "bbox_norm": [0.1, 0.2, 0.6, 0.7],
                            },
                            {
                                "roi_id": "fabric_zone",
                                "label": "Velvet pile",
                                "roi_type": "textile_weave",
                                "must_lock_base": False,
                                "bbox_norm": [0.5, 0.25, 0.9, 0.75],
                            },
                        ],
                    },
                    {
                        "asset_id": "mel_missing",
                        "filename": "does_not_exist.png",
                        "sha256": "a" * 64,
                        "category": "portraits",
                        "synthetic": False,
                        "ground_truth_eligible": True,
                        "critical_rois": [
                            {
                                "roi_id": "face",
                                "roi_type": "identity_landmark",
                                "must_lock_base": True,
                                "bbox_norm": [0.2, 0.2, 0.8, 0.8],
                            }
                        ],
                    },
                    {
                        "asset_id": "mel_synth",
                        "filename": "mel_sample.png",
                        "sha256": img_sha,
                        "category": "portraits",
                        "synthetic": True,
                        "ground_truth_eligible": False,
                        "critical_rois": [],
                    },
                ]
            }

            with self.assertRaises(FileNotFoundError):
                load_audition_cases_from_manifest(
                    melato_manifest, master_root=master_root, skip_missing=False
                )

            cases, summary = load_audition_cases_from_manifest(
                melato_manifest, master_root=master_root, skip_missing=True
            )
            self.assertEqual(summary["selected_count"], 1)
            self.assertEqual(summary["skipped_count"], 2)
            self.assertEqual(
                summary["skipped_reasons"],
                {"synthetic_excluded": 1, "source_missing": 1},
            )
            self.assertEqual(cases[0]["id"], "mel_sample")
            self.assertEqual(cases[0]["rois"][0]["kind"], "seam")
            self.assertEqual(cases[0]["rois"][0]["policy"], "preserve")
            self.assertEqual(cases[0]["rois"][0]["rect"], [2, 8, 10, 20])
            self.assertEqual(cases[0]["rois"][1]["kind"], "fabric")
            self.assertEqual(cases[0]["rois"][1]["policy"], "texture_allowed")

            corpus_manifest = {
                "cases": [
                    {
                        "case_id": "app_held_test",
                        "category": "apparel_model",
                        "split": "held_out",
                        "source": {
                            "storage": "off_repo",
                            "filename": "mel_sample.png",
                            "sha256": img_sha,
                        },
                        "critical_rois": [
                            {
                                "roi_id": "hw",
                                "roi_type": "hardware",
                                "must_lock_base": True,
                                "bbox_norm": [0.25, 0.25, 0.75, 0.75],
                            }
                        ],
                    },
                    {
                        "case_id": "missing_slot",
                        "category": "apparel_model",
                        "split": "held_out",
                        "availability": "missing",
                        "rights": {"cleared": False},
                        "source": {"relative_path": None, "sha256": None},
                        "critical_rois": [],
                    },
                    {
                        "case_id": "unannotated_slot",
                        "category": "textiles",
                        "split": "held_out",
                        "source": {
                            "storage": "off_repo",
                            "filename": "mel_sample.png",
                            "sha256": img_sha,
                        },
                        "critical_rois": [
                            {
                                "roi_id": "weave",
                                "roi_type": "textile_weave",
                                "must_lock_base": False,
                                "bbox_norm": None,
                            }
                        ],
                    },
                ]
            }
            held_cases, held_summary = load_audition_cases_from_manifest(
                corpus_manifest,
                master_root=master_root,
                split="held_out",
                skip_missing=True,
            )
            self.assertEqual(held_summary["selected_ids"], ["app_held_test"])
            self.assertEqual(
                held_summary["skipped_reasons"],
                {"source_missing": 1, "roi_unannotated": 1},
            )
            self.assertEqual(held_cases[0]["rois"][0]["kind"], "hardware")

            tampered = json.loads(json.dumps(corpus_manifest))
            tampered["cases"][0]["source"]["sha256"] = "0" * 64
            with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                load_audition_cases_from_manifest(
                    tampered, master_root=master_root, skip_missing=True
                )

            traversal = json.loads(json.dumps(corpus_manifest))
            traversal["cases"][0]["source"]["filename"] = "../outside.png"
            with self.assertRaisesRegex(ValueError, "Unsafe off-repo filename"):
                load_audition_cases_from_manifest(
                    traversal, master_root=master_root, skip_missing=True
                )

            manifest_path = root / "melato.json"
            manifest_path.write_text(json.dumps(melato_manifest), encoding="utf-8")
            proc = subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / "scripts" / "audition-melato.py"),
                    "--manifest",
                    str(manifest_path),
                    "--master-root",
                    str(master_root),
                    "--skip-missing",
                    "--backend",
                    "bicubic",
                    "--no-html",
                    "--output-dir",
                    str(root / "cli_out"),
                ],
                cwd=str(REPO_ROOT),
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
            cli_payload = json.loads(proc.stdout)
            self.assertEqual(cli_payload["manifest_resolution"]["selected_ids"], ["mel_sample"])
            self.assertEqual(cli_payload["summary"]["total_cases"], 1)
            self.assertTrue(Path(cli_payload["blind_ballot"]).is_file())


if __name__ == "__main__":
    unittest.main()
