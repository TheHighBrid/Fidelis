"""Unit tests for fidelis.studio.audition (F8) and CLI/Batch integration."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import numpy as np
from PIL import Image

from fidelis.engine import DimensionMismatchError, create_restoration_runner
from fidelis.studio.audition import (
    classify_audition_outcome,
    generate_side_by_side_crops,
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
            self.assertEqual((by_key[("full_frame", 1)]["width"], by_key[("full_frame", 1)]["height"]), (128, 64))
            self.assertEqual((by_key[("full_frame", 2)]["width"], by_key[("full_frame", 2)]["height"]), (256, 128))
            self.assertEqual((by_key[("crema", 1)]["width"], by_key[("crema", 1)]["height"]), (40, 16))
            self.assertEqual((by_key[("crema", 2)]["width"], by_key[("crema", 2)]["height"]), (80, 32))
            for c in crops:
                with Image.open(c["path"]) as im:
                    self.assertEqual((im.width, im.height), (c["width"], c["height"]))

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


if __name__ == "__main__":
    unittest.main()
