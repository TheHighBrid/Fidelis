"""Native-grid material, hardware, seam and exact-lock fidelity metrics."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import cv2
import numpy as np

from fidelis.eval.roi_normalization import normalize_rois_to_target as _normalize_rois_to_target
from fidelis.eval.texture_metrics import (
    _SPECTRAL_MEMORY_THRESHOLD,
    _bt709_luminance,
    _fft_power_spectrum,
)
from fidelis.postprocess.roi_protection import screen_internal_drift

_HW_SEAM_ROI_KINDS = frozenset({"hardware", "seam"})
_ORIENTATION_STRIP_ROWS = 256
_ORIENTATION_STRIP_PAD = 16


def _structure_tensors(yr, yc):
    ix_r = cv2.Sobel(yr, cv2.CV_32F, 1, 0, ksize=3)
    iy_r = cv2.Sobel(yr, cv2.CV_32F, 0, 1, ksize=3)
    ix_c = cv2.Sobel(yc, cv2.CV_32F, 1, 0, ksize=3)
    iy_c = cv2.Sobel(yc, cv2.CV_32F, 0, 1, ksize=3)
    return (
        cv2.GaussianBlur(ix_r * ix_r, (0, 0), 1.5),
        cv2.GaussianBlur(ix_r * iy_r, (0, 0), 1.5),
        cv2.GaussianBlur(iy_r * iy_r, (0, 0), 1.5),
        cv2.GaussianBlur(ix_c * ix_c, (0, 0), 1.5),
        cv2.GaussianBlur(ix_c * iy_c, (0, 0), 1.5),
        cv2.GaussianBlur(iy_c * iy_c, (0, 0), 1.5),
    )


def _orientation_coherence(yr, yc):
    height = yr.shape[0]
    masked = {"count": 0, "w_sum": 0.0, "wcos_sum": 0.0, "cos_sum": 0.0}
    all_px = {"count": 0, "w_sum": 0.0, "wcos_sum": 0.0, "cos_sum": 0.0}

    for y0 in range(0, height, _ORIENTATION_STRIP_ROWS):
        y1 = min(height, y0 + _ORIENTATION_STRIP_ROWS)
        sy0 = max(0, y0 - _ORIENTATION_STRIP_PAD)
        sy1 = min(height, y1 + _ORIENTATION_STRIP_PAD)
        jxx_r, jxy_r, jyy_r, jxx_c, jxy_c, jyy_c = _structure_tensors(yr[sy0:sy1], yc[sy0:sy1])
        sl = np.s_[y0 - sy0:y1 - sy0]
        jxx_r, jxy_r, jyy_r = jxx_r[sl], jxy_r[sl], jyy_r[sl]
        jxx_c, jxy_c, jyy_c = jxx_c[sl], jxy_c[sl], jyy_c[sl]

        theta_r = 0.5 * np.arctan2(2.0 * jxy_r, jxx_r - jyy_r)
        theta_c = 0.5 * np.arctan2(2.0 * jxy_c, jxx_c - jyy_c)
        trace_r = jxx_r + jyy_r
        coh_energy = np.sqrt((jxx_r - jyy_r) ** 2 + 4.0 * (jxy_r ** 2))
        aniso_r = coh_energy / (trace_r + 1e-6)
        cos2_diff = np.cos(2.0 * (theta_c - theta_r))
        weighted = coh_energy * cos2_diff

        all_px["count"] += cos2_diff.size
        all_px["w_sum"] += float(np.sum(coh_energy, dtype=np.float64))
        all_px["wcos_sum"] += float(np.sum(weighted, dtype=np.float64))
        all_px["cos_sum"] += float(np.sum(cos2_diff, dtype=np.float64))

        mask = (trace_r > 10.0) & (aniso_r > 0.15)
        if np.any(mask):
            masked["count"] += int(np.count_nonzero(mask))
            masked["w_sum"] += float(np.sum(coh_energy[mask], dtype=np.float64))
            masked["wcos_sum"] += float(np.sum(weighted[mask], dtype=np.float64))
            masked["cos_sum"] += float(np.sum(cos2_diff[mask], dtype=np.float64))

    chosen = masked if masked["count"] > 0 else all_px
    if chosen["w_sum"] > 1e-9:
        return float(chosen["wcos_sum"] / chosen["w_sum"])
    return float(chosen["cos_sum"] / max(chosen["count"], 1))


def _weave_spectrum(yr, yc, rh, rw):
    # 2D FFT periodicity coherence (exclude DC/very-low-frequency envelope r_px < 2)
    yr_zm = yr - float(np.mean(yr))
    yc_zm = yc - float(np.mean(yc))
    if yr_zm.size > _SPECTRAL_MEMORY_THRESHOLD:
        from fidelis.eval.spectral_memory import spectral_weave_coherence
        return spectral_weave_coherence(yr_zm, yc_zm)
    p_r = _fft_power_spectrum(yr_zm)
    p_c = _fft_power_spectrum(yc_zm)

    yy, xx = np.ogrid[:rh, :rw]
    cy, cx = rh // 2, rw // 2
    r_px = np.sqrt((yy - cy) ** 2 + (xx - cx) ** 2)
    hp_freq_mask = r_px >= 2.0

    p_r_hp = p_r * hp_freq_mask
    p_c_hp = p_c * hp_freq_mask
    sum_r = float(np.sum(p_r_hp))
    sum_c = float(np.sum(p_c_hp))

    if sum_r < 1e-9 and sum_c < 1e-9:
        fft_coh = 1.0
        energy_ratio = 1.0
    else:
        p_r_norm = p_r_hp / (sum_r + 1e-12)
        p_c_norm = p_c_hp / (sum_c + 1e-12)
        denom = float(np.linalg.norm(p_r_norm) * np.linalg.norm(p_c_norm))
        fft_coh = float(np.sum(p_r_norm * p_c_norm) / max(denom, 1e-12))
        energy_ratio = sum_c / max(sum_r, 1e-9)

    return fft_coh, energy_ratio


def _fabric_report(r, yc, yr):
    _, _, rw, rh = r["rect"]
    if rw < 4 or rh < 4:
        return {
            "id": r["id"],
            "rect": r["rect"],
            "weave_orientation_coherence": None,
            "weave_fft_coherence": None,
            "weave_energy_ratio": None,
            "passed": False,
            "reason": "fabric_roi_too_small_to_measure",
        }
    orient_coh = _orientation_coherence(yr, yc)
    fft_coh, energy_ratio = _weave_spectrum(yr, yc, rh, rw)
    roi_ok = orient_coh >= 0.80 and fft_coh >= 0.75 and energy_ratio >= 0.90
    return {
        "id": r["id"],
        "rect": r["rect"],
        "weave_orientation_coherence": round(orient_coh, 6),
        "weave_fft_coherence": round(fft_coh, 6),
        "weave_energy_ratio": round(energy_ratio, 6),
        "passed": bool(roi_ok),

    }


def _measure_fabric(norm_rois, candidate_rgb, bicubic_rgb):
    fabric_reports = []
    for r in norm_rois:
        if r["kind"] != "fabric":
            continue
        rx, ry, rw, rh = r["rect"]
        yr = _bt709_luminance(bicubic_rgb[ry:ry + rh, rx:rx + rw])
        yc = _bt709_luminance(candidate_rgb[ry:ry + rh, rx:rx + rw])
        fabric_reports.append(_fabric_report(r, yc, yr))
    fabric_passed = all(report["passed"] for report in fabric_reports)
    fabric_measurement_unavailable = any(report["weave_orientation_coherence"] is None for report in fabric_reports)
    return fabric_reports, fabric_passed, fabric_measurement_unavailable


def _hardware_drift(hw_seam_rois, bicubic_rgb, candidate_rgb, protected, master_rgb):
    drift_rois = [
        {
            "id": r["id"],
            "kind": r["drift_kind"],
            "policy": r["policy"],
            "override": r["override"],
            "rect": r["rect"],
            "label": r["label"],
        }
        for r in hw_seam_rois
    ]
    drift_res = screen_internal_drift(
        bicubic_rgb,
        candidate_rgb,
        rois=drift_rois,
        protected=protected,
        master=master_rgb,
        shift_warn_px=1.0,
        shift_fail_px=2.0,
        min_edge_coherence=0.85,
    )
    return drift_res


def _locked_mismatches_without_rois(bicubic_rgb, candidate_rgb, protected, master_rgb):
    h, w = bicubic_rgb.shape[:2]
    locked_mismatches = 0
    if protected is not None:
        prot_arr = np.asarray(protected, dtype=np.float32)
        if prot_arr.shape[:2] == (h, w):
            check_rgb = candidate_rgb
            if master_rgb is not None:
                for y0 in range(0, h, 256):
                    y1 = min(h, y0 + 256)
                    if not np.array_equal(master_rgb[y0:y1], bicubic_rgb[y0:y1]):
                        check_rgb = master_rgb
                        break
            for y0 in range(0, h, 256):
                y1 = min(h, y0 + 256)
                row_locked = prot_arr[y0:y1] == 1.0
                if np.any(row_locked):
                    locked_mismatches += int(
                        np.sum(np.any(check_rgb[y0:y1][row_locked] != bicubic_rgb[y0:y1][row_locked], axis=-1))
                    )

    return locked_mismatches


def _hardware_report(r, drep, candidate_rgb, bicubic_rgb, kernel5, locked_mismatches):
    h, w = bicubic_rgb.shape[:2]
    rx, ry, rw, rh = r["rect"]
    yc_roi = _bt709_luminance(candidate_rgb[ry:ry + rh, rx:rx + rw])
    px0, py0 = max(0, rx - 2), max(0, ry - 2)
    px1, py1 = min(w, rx + rw + 2), min(h, ry + rh + 2)
    y_bic_pad = _bt709_luminance(bicubic_rgb[py0:py1, px0:px1])
    ix0, iy0 = rx - px0, ry - py0
    lmax_roi = cv2.dilate(y_bic_pad, kernel5)[iy0:iy0 + rh, ix0:ix0 + rw]
    lmin_roi = cv2.erode(y_bic_pad, kernel5)[iy0:iy0 + rh, ix0:ix0 + rw]

    overshoot = np.maximum(0.0, yc_roi - lmax_roi)
    undershoot = np.maximum(0.0, lmin_roi - yc_roi)
    max_over = float(max(overshoot.max(), undershoot.max()))
    over_frac = float(np.mean(np.maximum(overshoot, undershoot) > 4.0))

    coh = drep["candidate_edge_coherence"]
    shift_px = float(drep["candidate_shift_px"])
    drift_ok = (
        drep["status"] not in ("FAIL_DRIFT", "LOCK_VIOLATION")
        and shift_px <= 1.0
        and (coh is None or coh >= 0.85)
    )
    overshoot_ok = max_over <= 8.0 and over_frac <= 0.02
    roi_ok = drift_ok and overshoot_ok and locked_mismatches == 0
    return {
        "id": r["id"],
        "kind": r["kind"],
        "rect": r["rect"],
        "drift_status": drep["status"],
        "candidate_shift_px": shift_px,
        "candidate_edge_coherence": coh,
        "max_overshoot_luma": round(max_over, 6),
        "overshoot_fraction": round(over_frac, 6),
        "passed": bool(roi_ok),

    }


def _measure_hardware(norm_rois, candidate_rgb, bicubic_rgb, protected, master_rgb):
    hw_seam_rois = [r for r in norm_rois if r["kind"] in _HW_SEAM_ROI_KINDS]
    if not hw_seam_rois:
        locked_mismatches = _locked_mismatches_without_rois(bicubic_rgb, candidate_rgb, protected, master_rgb)
        return [], locked_mismatches == 0, locked_mismatches
    drift_res = _hardware_drift(hw_seam_rois, bicubic_rgb, candidate_rgb, protected, master_rgb)
    locked_mismatches = int(drift_res["locked_pixel_mismatches"])
    kernel5 = np.ones((5, 5), np.uint8)
    hw_seam_reports = [
        _hardware_report(r, drep, candidate_rgb, bicubic_rgb, kernel5, locked_mismatches)
        for r, drep in zip(hw_seam_rois, drift_res["roi_reports"])
    ]
    passed = locked_mismatches == 0 and all(report["passed"] for report in hw_seam_reports)
    return hw_seam_reports, passed, locked_mismatches


def _material_unavailable(reason):
    return {
        "fabric_rois_evaluated": 0,
        "fabric_weave_passed": False,
        "fabric_reports": [],
        "hardware_seam_rois_evaluated": 0,
        "hardware_seam_passed": False,
        "locked_pixel_mismatches": 0,
        "hardware_seam_reports": [],
        "passed": False,
        "reason": reason,
    }


def measure_fabric_hardware_faithfulness(
    candidate_rgb: np.ndarray,
    bicubic_rgb: np.ndarray,
    *,
    rois: Sequence[Mapping[str, Any]] | None = None,
    protected: np.ndarray | None = None,
    master_rgb: np.ndarray | None = None,
) -> dict[str, Any]:
    """F4: Measure fabric weave orientation/FFT coherence and hardware/seam zero-drift & zero-overshoot."""
    h, w = bicubic_rgb.shape[:2]
    if h <= 0 or w <= 0:
        return _material_unavailable("empty_image_dimensions")
    if (
        not np.all(np.isfinite(candidate_rgb))
        or not np.all(np.isfinite(bicubic_rgb))
        or (master_rgb is not None and not np.all(np.isfinite(master_rgb)))
    ):
        return _material_unavailable("nonfinite_input")
    norm_rois = _normalize_rois_to_target(rois, (h, w), roi_space="target")

    fabric_reports, fabric_passed, fabric_measurement_unavailable = _measure_fabric(
        norm_rois, candidate_rgb, bicubic_rgb
    )
    hw_seam_reports, hw_seam_passed, locked_mismatches = _measure_hardware(
        norm_rois, candidate_rgb, bicubic_rgb, protected, master_rgb
    )
    return {
        "fabric_rois_evaluated": len(fabric_reports),
        "fabric_weave_passed": bool(fabric_passed),
        "fabric_measurement_unavailable": fabric_measurement_unavailable,
        "fabric_reports": fabric_reports,
        "hardware_seam_rois_evaluated": len(hw_seam_reports),
        "hardware_seam_passed": bool(hw_seam_passed),
        "locked_pixel_mismatches": locked_mismatches,
        "hardware_seam_reports": hw_seam_reports,
        "passed": bool(fabric_passed and hw_seam_passed),
    }
