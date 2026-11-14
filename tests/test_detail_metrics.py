"""Unit tests for native 4x scale-matched detail metrics (F2, F3, F4)."""

from __future__ import annotations

import unittest
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageFilter

from fidelis.eval.benchmark_suite import BenchmarkSuite
from fidelis.eval.detail_metrics import (
    measure_fabric_hardware_faithfulness,
    measure_interior_texture_retention,
    measure_oversharpening_restraint,
    measure_scale_matched_metrics,
)
from fidelis.eval.pipeline_metrics import measure_scale_matched_metrics as pm_measure_scale_matched

REPO = Path(__file__).resolve().parents[1]
COFFEE_CROP = REPO / "experiments/eval_crops/product_edges_real.png"
FABRIC_CROP = REPO / "experiments/eval_crops/fashion_fabric_real.png"


class DetailMetricsTests(unittest.TestCase):
    def test_f2_interior_texture_on_coffee_4x_smoothed_vs_lanczos(self) -> None:
        with Image.open(COFFEE_CROP) as im:
            src_rgb = im.convert("RGB")
            sw, sh = src_rgb.size
            target_size = (sw * 4, sh * 4)
            bic_im = src_rgb.resize(target_size, Image.Resampling.BICUBIC)
            lanczos_im = src_rgb.resize(target_size, Image.Resampling.LANCZOS)
            smoothed_im = bic_im.filter(ImageFilter.GaussianBlur(radius=1.2))

        bic_rgb = np.asarray(bic_im)
        lanczos_rgb = np.asarray(lanczos_im)
        smoothed_rgb = np.asarray(smoothed_im)

        res_bic = measure_interior_texture_retention(bic_rgb, bic_rgb)
        self.assertTrue(res_bic["passed"])
        self.assertAlmostEqual(res_bic["interior_texture_variance_ratio"], 1.0, places=5)
        self.assertAlmostEqual(res_bic["interior_midband_energy_ratio"], 1.0, places=5)

        res_smooth = measure_interior_texture_retention(smoothed_rgb, bic_rgb)
        self.assertFalse(res_smooth["passed"])
        self.assertEqual(res_smooth["reason"], "texture_smoothed_below_bicubic")
        self.assertLess(res_smooth["interior_texture_variance_ratio"], 1.0)
        self.assertLess(res_smooth["interior_midband_energy_ratio"], 1.0)

        res_lanczos = measure_interior_texture_retention(lanczos_rgb, bic_rgb)
        self.assertTrue(res_lanczos["passed"])
        self.assertGreaterEqual(res_lanczos["interior_texture_variance_ratio"], 1.0)
        self.assertGreaterEqual(res_lanczos["interior_midband_energy_ratio"], 1.0)

    def test_f3_oversharpening_halo_fails_while_clean_detail_passes(self) -> None:
        with Image.open(COFFEE_CROP) as im:
            src_rgb = im.convert("RGB")
            sw, sh = src_rgb.size
            target_size = (sw * 4, sh * 4)
            bic_im = src_rgb.resize(target_size, Image.Resampling.BICUBIC)
            lanczos_im = src_rgb.resize(target_size, Image.Resampling.LANCZOS)
            sharpened_im = bic_im.filter(ImageFilter.UnsharpMask(radius=1.5, percent=200, threshold=0))

        bic_rgb = np.asarray(bic_im)
        lanczos_rgb = np.asarray(lanczos_im)
        sharpened_rgb = np.asarray(sharpened_im)

        self.assertTrue(measure_oversharpening_restraint(bic_rgb, bic_rgb)["passed"])
        self.assertTrue(measure_oversharpening_restraint(lanczos_rgb, bic_rgb)["passed"])

        sharp_res = measure_oversharpening_restraint(sharpened_rgb, bic_rgb)
        self.assertFalse(sharp_res["passed"])
        self.assertEqual(sharp_res["reason"], "oversharpening_halo_ringing")
        self.assertGreater(sharp_res["contour_overshoot_p95"], 4.0)

    def test_f4_fabric_weave_coherence_and_hardware_seam_drift(self) -> None:
        # Synthetic directional diagonal weave + hard hardware edge
        h, w = 256, 256
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        weave = 128.0 + 45.0 * np.sin(2.0 * np.pi * (xx + yy) / 8.0)
        ref_rgb = np.stack([weave, weave, weave], axis=-1).clip(0, 255).astype(np.uint8)
        # Draw a crisp hardware bar in the bottom-right quadrant
        ref_rgb[160:224, 160:224] = 30
        ref_rgb[172:212, 172:212] = 225

        rois = [
            {"id": "fab1", "kind": "fabric", "policy": "texture_allowed", "rect": [16, 16, 112, 112]},
            {"id": "hw1", "kind": "hardware", "policy": "preserve", "rect": [152, 152, 80, 80]},
        ]

        # Exact match passes both fabric and hardware
        ok_res = measure_fabric_hardware_faithfulness(ref_rgb, ref_rgb, rois=rois)
        self.assertTrue(ok_res["fabric_weave_passed"])
        self.assertTrue(ok_res["hardware_seam_passed"])
        self.assertTrue(ok_res["passed"])

        # Orthogonal rotated weave (xx - yy instead of xx + yy) fails fabric orientation coherence
        bad_weave = 128.0 + 45.0 * np.sin(2.0 * np.pi * (xx - yy) / 8.0)
        bad_fab_rgb = ref_rgb.copy()
        bad_fab_rgb[16:128, 16:128] = np.stack([bad_weave, bad_weave, bad_weave], axis=-1).clip(0, 255).astype(np.uint8)[16:128, 16:128]
        bad_fab_res = measure_fabric_hardware_faithfulness(bad_fab_rgb, ref_rgb, rois=rois)
        self.assertFalse(bad_fab_res["fabric_weave_passed"])
        self.assertLess(bad_fab_res["fabric_reports"][0]["weave_orientation_coherence"], 0.80)

        # Shifted hardware ROI (3px shift) fails hardware_seam_passed
        shifted_hw = ref_rgb.copy()
        shifted_hw[152:232, 152:232] = np.roll(ref_rgb[152:232, 152:232], shift=3, axis=1)
        bad_hw_res = measure_fabric_hardware_faithfulness(shifted_hw, ref_rgb, rois=rois)
        self.assertFalse(bad_hw_res["hardware_seam_passed"])
        self.assertGreaterEqual(bad_hw_res["hardware_seam_reports"][0]["candidate_shift_px"], 2.0)

        # Locked-pixel mismatch fails hardware_seam_passed
        protected = np.zeros((h, w), dtype=np.float32)
        protected[160:224, 160:224] = 1.0
        tampered_master = ref_rgb.copy()
        tampered_master[180, 180] = [0, 0, 0]
        locked_fail = measure_fabric_hardware_faithfulness(
            ref_rgb, ref_rgb, rois=rois, protected=protected, master_rgb=tampered_master
        )
        self.assertFalse(locked_fail["hardware_seam_passed"])
        self.assertGreater(locked_fail["locked_pixel_mismatches"], 0)

    def test_benchmark_suite_evaluate_4x_detail_and_dimension_mismatch(self) -> None:
        with Image.open(FABRIC_CROP) as im:
            src_rgb = np.asarray(im.convert("RGB"))
            sh, sw = src_rgb.shape[:2]
            bic_rgb = np.asarray(im.convert("RGB").resize((sw * 4, sh * 4), Image.Resampling.BICUBIC))

        rois_1x = [{"id": "fab_roi", "kind": "fabric", "policy": "texture_allowed", "rect": [10, 10, sw - 20, sh - 20]}]
        suite = BenchmarkSuite()
        rep = suite.evaluate_4x_detail(src_rgb, bic_rgb, rois=rois_1x)
        self.assertEqual(rep["status"], "measured")
        self.assertEqual(rep["native_dimensions"], [sw * 4, sh * 4])
        self.assertTrue(rep["all_detail_gates_passed"])
        self.assertEqual(rep["fabric_hardware"]["fabric_rois_evaluated"], 1)

        # Dimension mismatch must fail closed without silent resizing
        wrong_bgr = np.zeros((100, 100, 3), dtype=np.uint8)
        bic_bgr = cv2.cvtColor(bic_rgb, cv2.COLOR_RGB2BGR)
        mismatch = pm_measure_scale_matched(wrong_bgr, bic_bgr)
        self.assertEqual(mismatch["status"], "unavailable")
        self.assertEqual(mismatch["reason"], "dimension_mismatch_silent_resizing_forbidden")
        self.assertFalse(mismatch["all_detail_gates_passed"])
        self.assertIs(pm_measure_scale_matched, measure_scale_matched_metrics)


if __name__ == "__main__":
    unittest.main()
