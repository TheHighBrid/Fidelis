"""Bit-exactness and strip-boundary equivalence tests for bounded composition, drift, and material metrics (#129)."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from fidelis.eval import material_metrics, spectral_memory
from fidelis.eval.material_metrics import measure_fabric_hardware_faithfulness
from fidelis.postprocess import regions, roi_protection


def _reference_compose(
    base,
    texture,
    *,
    skin=None,
    hair=None,
    fabric=None,
    protected=None,
    confidence=None,
    edge_guard=None,
    interior_texture=None,
    blend=None,
    output_dtype=None,
):
    if blend is None:
        blend = regions.RegionBlend()
    target_dtype = np.dtype(output_dtype if output_dtype is not None else base.dtype)
    source_max = np.iinfo(base.dtype).max
    output_max = np.iinfo(target_dtype).max
    shape = base.shape[:2]

    def _m(v):
        return np.zeros(shape, dtype=np.float32) if v is None else np.asarray(v, dtype=np.float32)

    skin_m, hair_m, fabric_m = _m(skin), _m(hair), _m(fabric)
    prot_m, conf_m, edge_m = _m(protected), _m(confidence), _m(edge_guard)
    if interior_texture is not None:
        edge_m = edge_m * (1.0 - _m(interior_texture))
    total = np.maximum(1.0, skin_m + hair_m + fabric_m)
    alpha = (skin_m * blend.skin + hair_m * blend.hair + fabric_m * blend.fabric) / total
    alpha *= conf_m * (1.0 - prot_m)
    alpha *= 1.0 - edge_m * blend.edge_protection
    alpha = np.clip(alpha, 0.0, 1.0)

    def _lin(img):
        smax = np.iinfo(img.dtype).max
        srgb = np.arange(smax + 1, dtype=np.float32) / smax
        return np.where(srgb <= 0.04045, srgb / 12.92, ((srgb + 0.055) / 1.055) ** 2.4)[img]

    linear = _lin(base) * (1.0 - alpha[..., None]) + _lin(texture) * alpha[..., None]
    srgb = np.where(
        linear <= 0.0031308,
        linear * 12.92,
        1.055 * np.maximum(linear, 0) ** (1 / 2.4) - 0.055,
    )
    res = np.clip(np.rint(srgb * output_max), 0, output_max).astype(target_dtype)
    locked = (prot_m == 1.0) | (alpha == 0.0)
    res[locked] = base[locked].astype(target_dtype) * (output_max // source_max)
    return res, alpha


class BoundedCompositionDriftTests(unittest.TestCase):
    def test_strip_compose_matches_full_frame_bit_for_bit_across_dtypes(self) -> None:
        rng = np.random.default_rng(129)
        h, w = 290, 173
        base8 = rng.integers(0, 256, (h, w, 3), dtype=np.uint8)
        tex8 = rng.integers(0, 256, (h, w, 3), dtype=np.uint8)
        skin = rng.uniform(0.0, 1.0, (h, w)).astype(np.float32)
        fabric = rng.uniform(0.0, 1.0, (h, w)).astype(np.float32)
        prot = (rng.uniform(0.0, 1.0, (h, w)) > 0.85).astype(np.float32)
        conf = rng.uniform(0.0, 1.0, (h, w)).astype(np.float32)
        edge = rng.uniform(0.0, 1.0, (h, w)).astype(np.float32)
        interior = (rng.uniform(0.0, 1.0, (h, w)) > 0.5).astype(np.float32)
        blend = regions.RegionBlend(skin=0.3, hair=0.2, fabric=0.4, edge_protection=0.6)

        with patch.object(regions, "_COMPOSE_STRIP_ROWS", 64):
            actual8, alpha8 = regions.compose_regions(
                base8,
                tex8,
                skin=skin,
                hair=None,
                fabric=fabric,
                protected=prot,
                confidence=conf,
                edge_guard=edge,
                interior_texture=interior,
                blend=blend,
            )
        ref8, ref_alpha8 = _reference_compose(
            base8,
            tex8,
            skin=skin,
            hair=None,
            fabric=fabric,
            protected=prot,
            confidence=conf,
            edge_guard=edge,
            interior_texture=interior,
            blend=blend,
        )
        np.testing.assert_array_equal(actual8, ref8)
        np.testing.assert_array_equal(alpha8, ref_alpha8)

        base16 = rng.integers(0, 65536, (h, w, 3), dtype=np.uint16)
        tex16 = rng.integers(0, 65536, (h, w, 3), dtype=np.uint16)
        with patch.object(regions, "_COMPOSE_STRIP_ROWS", 64):
            actual16, alpha16 = regions.compose_regions(
                base16,
                tex16,
                fabric=fabric,
                protected=prot,
                confidence=conf,
                blend=blend,
                output_dtype=np.uint16,
            )
        ref16, ref_alpha16 = _reference_compose(
            base16,
            tex16,
            fabric=fabric,
            protected=prot,
            confidence=conf,
            blend=blend,
            output_dtype=np.uint16,
        )
        np.testing.assert_array_equal(actual16, ref16)
        np.testing.assert_array_equal(alpha16, ref_alpha16)

    def test_strip_edge_guard_and_windowed_drift_match_full_frame_reference(self) -> None:
        rng = np.random.default_rng(130)
        h, w = 200, 180
        base = rng.integers(0, 256, (h, w, 3), dtype=np.uint8)
        cand = base.copy()
        # Shift an interior band by 2px so drift blocks and ROIs trigger across strip boundaries.
        cand[50:140, 20:160] = np.roll(base[50:140, 20:160], shift=2, axis=1)
        master = cand.copy()
        master[0:10, 0:10] = base[0:10, 0:10]

        rois = [
            {"id": "corner_lock", "kind": "logo", "policy": "preserve", "override": None, "rect": [0, 0, 24, 24]},
            {"id": "edge_seam", "kind": "seam", "policy": "preserve", "override": None, "rect": [1, 60, 30, 32]},
            {"id": "mid_fabric", "kind": "fabric", "policy": "texture_allowed", "override": None, "rect": [40, 56, 48, 48]},
            {"id": "bottom_hw", "kind": "hardware", "policy": "preserve", "override": None, "rect": [w - 28, h - 28, 28, 28]},
        ]
        with patch.object(roi_protection, "_DRIFT_STRIP_ROWS", 32):
            masks, _ = roi_protection.build_roi_protection_masks(base, rois, use_sobel_heuristic=True)
            report = roi_protection.screen_internal_drift(
                base,
                cand,
                rois=rois,
                protected=masks["protected"],
                master=master,
                block_size=32,
                search_radius=4,
            )

        # Reference full-frame Sobel edge guard and full-frame drift luminance/gradients
        lum = roi_protection._luminance(base)
        gx, gy, mag = roi_protection._gradients(lum)
        ref_scale = max(float(np.percentile(mag, 95)), 25.0)
        expected_sobel = np.clip((mag / ref_scale) * 0.35, 0.0, 0.65).astype(np.float32)
        expected_sobel[masks["interior_texture"] == 1.0] = 0.0
        np.testing.assert_array_equal(masks["edge_guard"], expected_sobel)

        ref_cand_lum = roi_protection._luminance(cand)
        ref_cand_grads = roi_protection._gradients(ref_cand_lum)
        for rrep, roi in zip(report["roi_reports"], rois):
            x, y, rw, rh = roi["rect"]
            dx, dy, imp = roi_protection._estimate_patch_shift(lum, ref_cand_lum, y, x, y + rh, x + rw, 4)
            coh = roi_protection._gradient_coherence(
                gx[y:y + rh, x:x + rw],
                gy[y:y + rh, x:x + rw],
                mag[y:y + rh, x:x + rw],
                ref_cand_grads[0][y:y + rh, x:x + rw],
                ref_cand_grads[1][y:y + rh, x:x + rw],
                ref_cand_grads[2][y:y + rh, x:x + rw],
            )
            self.assertEqual(rrep["candidate_shift_vec"], [dx, dy])
            self.assertEqual(rrep["candidate_shift_improvement"], round(imp, 3))
            self.assertEqual(rrep["candidate_edge_coherence"], round(coh, 4) if coh is not None else None)
        self.assertGreater(report["locked_pixel_mismatches"], 0)

    def test_roi_cropped_material_metrics_match_full_frame_dilate_and_erode(self) -> None:
        rng = np.random.default_rng(131)
        h, w = 310, 190
        bic = rng.integers(0, 256, (h, w, 3), dtype=np.uint8)
        cand = np.clip(bic.astype(np.int16) + rng.integers(-12, 13, (h, w, 3)), 0, 255).astype(np.uint8)
        rois = [
            {"id": "edge_hw", "kind": "hardware", "policy": "preserve", "override": None, "rect": [0, 1, 24, 24]},
            {"id": "far_seam", "kind": "seam", "policy": "preserve", "override": None, "rect": [w - 20, h - 22, 20, 22]},
            {"id": "weave", "kind": "fabric", "policy": "texture_allowed", "override": None, "rect": [30, 40, 64, 64]},
        ]
        res = measure_fabric_hardware_faithfulness(cand, bic, rois=rois)

        # Reference full-frame luminance + dilate/erode
        y_bic = 0.2126 * bic[:, :, 0].astype(np.float32) + 0.7152 * bic[:, :, 1].astype(np.float32) + 0.0722 * bic[:, :, 2].astype(np.float32)
        y_cand = 0.2126 * cand[:, :, 0].astype(np.float32) + 0.7152 * cand[:, :, 1].astype(np.float32) + 0.0722 * cand[:, :, 2].astype(np.float32)
        k5 = np.ones((5, 5), np.uint8)
        lmax = cv2.dilate(y_bic, k5)
        lmin = cv2.erode(y_bic, k5)
        for hrep, roi in zip(res["hardware_seam_reports"], rois[:2]):
            rx, ry, rw, rh = roi["rect"]
            over = np.maximum(0.0, y_cand[ry:ry + rh, rx:rx + rw] - lmax[ry:ry + rh, rx:rx + rw])
            under = np.maximum(0.0, lmin[ry:ry + rh, rx:rx + rw] - y_cand[ry:ry + rh, rx:rx + rw])
            self.assertEqual(hrep["max_overshoot_luma"], round(float(max(over.max(), under.max())), 6))
            self.assertEqual(hrep["overshoot_fraction"], round(float(np.mean(np.maximum(over, under) > 4.0)), 6))

    def test_bounded_orientation_and_weave_spectrum_match_reference(self) -> None:
        rng = np.random.default_rng(132)
        for h, w in ((137, 193), (128, 160)):
            with self.subTest(shape=(h, w)):
                yr = rng.uniform(0.0, 255.0, (h, w)).astype(np.float32)
                yc = np.clip(yr + rng.normal(0.0, 4.0, (h, w)).astype(np.float32), 0.0, 255.0)
                with patch.object(material_metrics, "_ORIENTATION_STRIP_ROWS", 32):
                    coh = material_metrics._orientation_coherence(yr, yc)
                jxx_r, jxy_r, jyy_r, jxx_c, jxy_c, jyy_c = material_metrics._structure_tensors(yr, yc)
                tr = jxx_r + jyy_r
                ce = np.sqrt((jxx_r - jyy_r) ** 2 + 4.0 * (jxy_r ** 2))
                mask = (tr > 10.0) & ((ce / (tr + 1e-6)) > 0.15)
                th_r = 0.5 * np.arctan2(2.0 * jxy_r, jxx_r - jyy_r)
                th_c = 0.5 * np.arctan2(2.0 * jxy_c, jxx_c - jyy_c)
                ref_coh = float(np.sum(ce[mask] * np.cos(2.0 * (th_c[mask] - th_r[mask]))) / np.sum(ce[mask]))
                self.assertAlmostEqual(coh, ref_coh, places=5)

                ref_fft, ref_ratio = material_metrics._weave_spectrum(yr, yc, h, w)
                with patch.object(material_metrics, "_SPECTRAL_MEMORY_THRESHOLD", 0):
                    bnd_fft, bnd_ratio = material_metrics._weave_spectrum(yr, yc, h, w)
                self.assertAlmostEqual(bnd_fft, ref_fft, places=5)
                self.assertAlmostEqual(bnd_ratio, ref_ratio, places=5)

        flat = np.full((64, 64), 120.0, dtype=np.float32)
        with patch.object(material_metrics, "_ORIENTATION_STRIP_ROWS", 16):
            self.assertAlmostEqual(material_metrics._orientation_coherence(flat, flat), 1.0, places=6)
        with patch.object(material_metrics, "_SPECTRAL_MEMORY_THRESHOLD", 0):
            self.assertEqual(material_metrics._weave_spectrum(flat, flat, 64, 64), (1.0, 1.0))

    def test_spectral_weave_coherence_cleans_scratch_on_error(self) -> None:
        arr = np.ones((16, 16), dtype=np.float32)
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(spectral_memory, "_column_transform", side_effect=OSError("io fail")):
                with self.assertRaisesRegex(OSError, "io fail"):
                    spectral_memory.spectral_weave_coherence(arr, arr, scratch_dir=directory, block_size=4)
            self.assertEqual(list(Path(directory).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
