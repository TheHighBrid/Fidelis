"""Native 4x scale-matched detail metrics (F2, F3, F4) for Fidelis evaluation.

All metrics operate strictly on the native target (e.g. 4x) grid comparing
``candidate`` against a ``bicubic`` 4x reference without downsampling the
candidate to 1x.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional, Sequence

import cv2
import numpy as np

from fidelis.postprocess.roi_protection import (
    VALID_POLICIES,
    VALID_ROI_KINDS,
    screen_internal_drift,
)

_TEXTURE_ROI_KINDS = frozenset({"fabric", "crema", "skin", "hair"})
_CONTOUR_ROI_KINDS = frozenset({"hardware", "seam", "logo", "text"})
_HW_SEAM_ROI_KINDS = frozenset({"hardware", "seam"})


def _bt709_luminance(rgb: np.ndarray) -> np.ndarray:
    arr = rgb.astype(np.float32)
    return 0.2126 * arr[:, :, 0] + 0.7152 * arr[:, :, 1] + 0.0722 * arr[:, :, 2]


def _normalize_rois_to_target(
    rois: Optional[Sequence[Mapping[str, Any]]],
    target_shape: tuple[int, int],
    source_shape: Optional[tuple[int, int]] = None,
    roi_space: str = "auto",
) -> list[dict[str, Any]]:
    """Normalize ROI dicts (``rect`` or ``bbox``) into target-grid ``rect: [x, y, w, h]``."""
    if not rois:
        return []
    th, tw = target_shape
    if roi_space not in ("auto", "source", "target"):
        raise ValueError(f"Unsupported roi_space {roi_space!r}")

    scale_x = 1.0
    scale_y = 1.0
    if source_shape is not None and roi_space in ("auto", "source"):
        sh, sw = source_shape
        if sw > 0 and sh > 0 and (roi_space == "source" or tw != sw or th != sh):
            scale_x = tw / float(sw)
            scale_y = th / float(sh)

    normalized: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for idx, entry in enumerate(rois):
        if not isinstance(entry, Mapping):
            continue
        kind = str(entry.get("kind", "fabric"))
        if kind not in VALID_ROI_KINDS:
            # Allow domain-specific aliases like "crema" for interior texture ROIs,
            # mapping unknown kinds safely for roi_protection compatibility.
            roi_kind_for_drift = "background" if kind == "crema" else kind
        else:
            roi_kind_for_drift = kind

        raw_policy = entry.get("policy")
        if raw_policy in VALID_POLICIES:
            policy = str(raw_policy)
        elif kind in _CONTOUR_ROI_KINDS or kind == "identity":
            policy = "preserve"
        else:
            policy = "texture_allowed"

        override = entry.get("override")
        if override not in (None, "lock", "unlock"):
            override = None

        if "rect" in entry and isinstance(entry["rect"], (list, tuple)) and len(entry["rect"]) == 4:
            rx, ry, rw, rh = [float(v) for v in entry["rect"]]
        elif "bbox" in entry and isinstance(entry["bbox"], (list, tuple)) and len(entry["bbox"]) == 4:
            x0, y0, x1, y1 = [float(v) for v in entry["bbox"]]
            rx, ry, rw, rh = x0, y0, x1 - x0, y1 - y0
        else:
            continue

        tx = int(round(rx * scale_x))
        ty = int(round(ry * scale_y))
        tw_r = int(round(rw * scale_x))
        th_r = int(round(rh * scale_y))

        if tw_r <= 0 or th_r <= 0:
            continue

        x0_c = max(0, tx)
        y0_c = max(0, ty)
        x1_c = min(tw, tx + tw_r)
        y1_c = min(th, ty + th_r)
        if x1_c <= x0_c or y1_c <= y0_c:
            continue

        tx = x0_c
        ty = y0_c
        tw_r = x1_c - x0_c
        th_r = y1_c - y0_c

        rid = str(entry.get("id") or f"roi_{idx}").strip() or f"roi_{idx}"
        while rid in seen_ids:
            rid = f"{rid}_{idx}"
        seen_ids.add(rid)

        normalized.append(
            {
                "id": rid,
                "kind": kind,
                "drift_kind": roi_kind_for_drift,
                "policy": policy,
                "override": override,
                "rect": [tx, ty, tw_r, th_r],
                "label": str(entry.get("label", rid)),
            }
        )
    return normalized


def _radial_frequency_grid(height: int, width: int) -> np.ndarray:
    fy = np.fft.fftshift(np.fft.fftfreq(height))
    fx = np.fft.fftshift(np.fft.fftfreq(width))
    return np.sqrt(fy[:, None] ** 2 + fx[None, :] ** 2)


def _fft_power_spectrum(signal: np.ndarray) -> np.ndarray:
    h, w = signal.shape
    win = np.outer(np.hanning(h), np.hanning(w)).astype(np.float32)
    spec = np.fft.fftshift(np.fft.fft2(signal * win))
    return (np.abs(spec) ** 2) / max(float(h * w), 1.0)


def measure_interior_texture_retention(
    candidate_rgb: np.ndarray,
    bicubic_rgb: np.ndarray,
    *,
    rois: Optional[Sequence[Mapping[str, Any]]] = None,
) -> dict[str, Any]:
    """F2: Measure native 4x interior texture variance & mid-band spectral energy vs bicubic."""
    h, w = bicubic_rgb.shape[:2]
    if h <= 0 or w <= 0:
        return {
            "interior_texture_variance_ratio": 0.0,
            "interior_midband_energy_ratio": 0.0,
            "interior_pixel_count": 0,
            "passed": False,
            "reason": "empty_image_dimensions",
        }
    if not np.all(np.isfinite(candidate_rgb)) or not np.all(np.isfinite(bicubic_rgb)):
        return {
            "interior_texture_variance_ratio": 0.0,
            "interior_midband_energy_ratio": 0.0,
            "interior_pixel_count": 0,
            "passed": False,
            "reason": "nonfinite_input",
        }
    y_cand = _bt709_luminance(candidate_rgb)
    y_bic = _bt709_luminance(bicubic_rgb)

    gx = cv2.Sobel(y_bic, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(y_bic, cv2.CV_32F, 0, 1, ksize=3)
    mag_ref = np.sqrt(gx * gx + gy * gy)

    norm_rois = _normalize_rois_to_target(rois, (h, w), roi_space="target")
    texture_rois = [
        r for r in norm_rois
        if r["policy"] == "texture_allowed" or r["kind"] in _TEXTURE_ROI_KINDS
    ]
    if texture_rois:
        pool_mask = np.zeros((h, w), dtype=bool)
        for r in texture_rois:
            rx, ry, rw, rh = r["rect"]
            pool_mask[ry:ry + rh, rx:rx + rw] = True
        for r in norm_rois:
            if (r["policy"] == "preserve" or r["override"] == "lock" or r["kind"] in _CONTOUR_ROI_KINDS) and r["override"] != "unlock":
                rx, ry, rw, rh = r["rect"]
                pool_mask[ry:ry + rh, rx:rx + rw] = False
        if int(pool_mask.sum()) == 0:
            return {
                "interior_texture_variance_ratio": 0.0,
                "interior_midband_energy_ratio": 0.0,
                "interior_pixel_count": 0,
                "passed": False,
                "reason": "empty_texture_roi_pool",
            }
    else:
        pool_mask = np.ones((h, w), dtype=bool)

    mag_pool = mag_ref[pool_mask]
    low_t = max(2.0, float(np.percentile(mag_pool, 25)))
    high_t = max(low_t + 1.0, float(np.percentile(mag_pool, 80)))
    interior_mask = pool_mask & (mag_ref >= low_t) & (mag_ref <= high_t)
    min_interior = min(64, max(1, int(pool_mask.sum()) // 2))
    if int(interior_mask.sum()) < min_interior:
        interior_mask = pool_mask

    hp_cand = y_cand - cv2.GaussianBlur(y_cand, (0, 0), sigmaX=2.0)
    hp_bic = y_bic - cv2.GaussianBlur(y_bic, (0, 0), sigmaX=2.0)

    var_cand = float(np.var(hp_cand[interior_mask]))
    var_bic = float(np.var(hp_bic[interior_mask]))
    if var_bic < 1e-6 and var_cand < 1e-6:
        var_ratio = 1.0
    else:
        var_ratio = var_cand / max(var_bic, 1e-6)

    sig_cand = (hp_cand - float(np.mean(hp_cand[interior_mask]))) * interior_mask
    sig_bic = (hp_bic - float(np.mean(hp_bic[interior_mask]))) * interior_mask

    p_cand = _fft_power_spectrum(sig_cand)
    p_bic = _fft_power_spectrum(sig_bic)
    r_grid = _radial_frequency_grid(h, w)
    mid_band = (r_grid >= 0.06) & (r_grid <= 0.25)

    if np.any(mid_band):
        e_mid_cand = float(np.mean(p_cand[mid_band]))
        e_mid_bic = float(np.mean(p_bic[mid_band]))
    else:
        e_mid_cand = 0.0
        e_mid_bic = 0.0

    if e_mid_bic < 1e-9 and e_mid_cand < 1e-9:
        midband_ratio = 1.0
    else:
        midband_ratio = e_mid_cand / max(e_mid_bic, 1e-9)

    passed = (var_ratio >= 1.0) and (midband_ratio >= 1.0)
    return {
        "interior_texture_variance_ratio": round(var_ratio, 6),
        "interior_midband_energy_ratio": round(midband_ratio, 6),
        "interior_pixel_count": int(interior_mask.sum()),
        "passed": bool(passed),
        "reason": None if passed else "texture_smoothed_below_bicubic",
    }


def measure_oversharpening_restraint(
    candidate_rgb: np.ndarray,
    bicubic_rgb: np.ndarray,
    *,
    rois: Optional[Sequence[Mapping[str, Any]]] = None,
) -> dict[str, Any]:
    """F3: Detect oversharpening halos, edge overshoot/undershoot, and Nyquist spikes."""
    h, w = bicubic_rgb.shape[:2]
    if h <= 0 or w <= 0:
        return {
            "contour_overshoot_mean": 0.0,
            "contour_overshoot_p95": 0.0,
            "contour_overshoot_frac": 0.0,
            "contour_nyquist_to_midband_ratio": 0.0,
            "contour_nyquist_gain_vs_bicubic": 0.0,
            "contour_pixel_count": 0,
            "passed": False,
            "reason": "empty_image_dimensions",
        }
    if not np.all(np.isfinite(candidate_rgb)) or not np.all(np.isfinite(bicubic_rgb)):
        return {
            "contour_overshoot_mean": 0.0,
            "contour_overshoot_p95": 0.0,
            "contour_overshoot_frac": 0.0,
            "contour_nyquist_to_midband_ratio": 0.0,
            "contour_nyquist_gain_vs_bicubic": 0.0,
            "contour_pixel_count": 0,
            "passed": False,
            "reason": "nonfinite_input",
        }
    y_cand = _bt709_luminance(candidate_rgb)
    y_bic = _bt709_luminance(bicubic_rgb)

    gx = cv2.Sobel(y_bic, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(y_bic, cv2.CV_32F, 0, 1, ksize=3)
    mag_ref = np.sqrt(gx * gx + gy * gy)

    norm_rois = _normalize_rois_to_target(rois, (h, w), roi_space="target")
    roi_mask: Optional[np.ndarray] = None
    if norm_rois:
        roi_mask = np.zeros((h, w), dtype=bool)
        for r in norm_rois:
            rx, ry, rw, rh = r["rect"]
            roi_mask[ry:ry + rh, rx:rx + rw] = True

    mag_scope = mag_ref[roi_mask] if roi_mask is not None else mag_ref
    edge_thresh = max(12.0, float(np.percentile(mag_scope, 90)))
    contour_core = (mag_ref >= edge_thresh) & (roi_mask if roi_mask is not None else True)
    if not np.any(contour_core):
        contour_band = roi_mask if roi_mask is not None else np.ones((h, w), dtype=bool)
    else:
        kernel5 = np.ones((5, 5), np.uint8)
        contour_band = cv2.dilate(contour_core.astype(np.uint8), kernel5, iterations=1) > 0
        if roi_mask is not None:
            contour_band = contour_band & roi_mask

    kernel5 = np.ones((5, 5), np.uint8)
    local_max = cv2.dilate(y_bic, kernel5)
    local_min = cv2.erode(y_bic, kernel5)
    excursion = np.maximum(0.0, y_cand - local_max) + np.maximum(0.0, local_min - y_cand)

    band_exc = excursion[contour_band]
    overshoot_mean = float(np.mean(band_exc))
    overshoot_p95 = float(np.percentile(band_exc, 95))
    overshoot_frac = float(np.mean(band_exc > 2.0))

    hp_cand = y_cand - cv2.GaussianBlur(y_cand, (0, 0), sigmaX=2.0)
    hp_bic = y_bic - cv2.GaussianBlur(y_bic, (0, 0), sigmaX=2.0)
    sig_c = (hp_cand - float(np.mean(hp_cand[contour_band]))) * contour_band
    sig_b = (hp_bic - float(np.mean(hp_bic[contour_band]))) * contour_band

    p_c = _fft_power_spectrum(sig_c)
    p_b = _fft_power_spectrum(sig_b)
    r_grid = _radial_frequency_grid(h, w)
    nyq_band = (r_grid > 0.25) & (r_grid <= 0.50)
    mid_band = (r_grid >= 0.06) & (r_grid <= 0.25)

    e_nyq_c = float(np.mean(p_c[nyq_band])) if np.any(nyq_band) else 0.0
    e_mid_c = float(np.mean(p_c[mid_band])) if np.any(mid_band) else 0.0
    e_nyq_b = float(np.mean(p_b[nyq_band])) if np.any(nyq_band) else 0.0
    e_mid_b = float(np.mean(p_b[mid_band])) if np.any(mid_band) else 0.0

    ratio_c = e_nyq_c / max(e_mid_c, 1e-9)
    ratio_b = e_nyq_b / max(e_mid_b, 1e-9)
    if ratio_b < 1e-9 and ratio_c < 1e-9:
        nyquist_gain = 1.0
    else:
        nyquist_gain = ratio_c / max(ratio_b, 1e-9)

    failed = (
        overshoot_p95 > 4.0
        or overshoot_frac > 0.05
        or (nyquist_gain > 3.0 and overshoot_mean > 0.5)
    )
    return {
        "contour_overshoot_mean": round(overshoot_mean, 6),
        "contour_overshoot_p95": round(overshoot_p95, 6),
        "contour_overshoot_frac": round(overshoot_frac, 6),
        "contour_nyquist_to_midband_ratio": round(ratio_c, 6),
        "contour_nyquist_gain_vs_bicubic": round(nyquist_gain, 6),
        "contour_pixel_count": int(contour_band.sum()),
        "passed": not failed,
        "reason": "oversharpening_halo_ringing" if failed else None,
    }


def measure_fabric_hardware_faithfulness(
    candidate_rgb: np.ndarray,
    bicubic_rgb: np.ndarray,
    *,
    rois: Optional[Sequence[Mapping[str, Any]]] = None,
    protected: Optional[np.ndarray] = None,
    master_rgb: Optional[np.ndarray] = None,
) -> dict[str, Any]:
    """F4: Measure fabric weave orientation/FFT coherence and hardware/seam zero-drift & zero-overshoot."""
    h, w = bicubic_rgb.shape[:2]
    if h <= 0 or w <= 0:
        return {
            "fabric_rois_evaluated": 0,
            "fabric_weave_passed": False,
            "fabric_reports": [],
            "hardware_seam_rois_evaluated": 0,
            "hardware_seam_passed": False,
            "locked_pixel_mismatches": 0,
            "hardware_seam_reports": [],
            "passed": False,
            "reason": "empty_image_dimensions",
        }
    if (
        not np.all(np.isfinite(candidate_rgb))
        or not np.all(np.isfinite(bicubic_rgb))
        or (master_rgb is not None and not np.all(np.isfinite(master_rgb)))
    ):
        return {
            "fabric_rois_evaluated": 0,
            "fabric_weave_passed": False,
            "fabric_reports": [],
            "hardware_seam_rois_evaluated": 0,
            "hardware_seam_passed": False,
            "locked_pixel_mismatches": 0,
            "hardware_seam_reports": [],
            "passed": False,
            "reason": "nonfinite_input",
        }
    norm_rois = _normalize_rois_to_target(rois, (h, w), roi_space="target")

    y_cand = _bt709_luminance(candidate_rgb)
    y_bic = _bt709_luminance(bicubic_rgb)

    # 1. Fabric weave coherence
    fabric_rois = [r for r in norm_rois if r["kind"] == "fabric"]
    fabric_reports: list[dict[str, Any]] = []
    fabric_passed = True

    for r in fabric_rois:
        rx, ry, rw, rh = r["rect"]
        yr = y_bic[ry:ry + rh, rx:rx + rw]
        yc = y_cand[ry:ry + rh, rx:rx + rw]

        if rw < 4 or rh < 4:
            fabric_reports.append(
                {
                    "id": r["id"],
                    "rect": r["rect"],
                    "weave_orientation_coherence": 1.0,
                    "weave_fft_coherence": 1.0,
                    "weave_energy_ratio": 1.0,
                    "passed": True,
                }
            )
            continue

        ix_r = cv2.Sobel(yr, cv2.CV_32F, 1, 0, ksize=3)
        iy_r = cv2.Sobel(yr, cv2.CV_32F, 0, 1, ksize=3)
        ix_c = cv2.Sobel(yc, cv2.CV_32F, 1, 0, ksize=3)
        iy_c = cv2.Sobel(yc, cv2.CV_32F, 0, 1, ksize=3)

        jxx_r = cv2.GaussianBlur(ix_r * ix_r, (0, 0), 1.5)
        jxy_r = cv2.GaussianBlur(ix_r * iy_r, (0, 0), 1.5)
        jyy_r = cv2.GaussianBlur(iy_r * iy_r, (0, 0), 1.5)

        jxx_c = cv2.GaussianBlur(ix_c * ix_c, (0, 0), 1.5)
        jxy_c = cv2.GaussianBlur(ix_c * iy_c, (0, 0), 1.5)
        jyy_c = cv2.GaussianBlur(iy_c * iy_c, (0, 0), 1.5)

        theta_r = 0.5 * np.arctan2(2.0 * jxy_r, jxx_r - jyy_r)
        theta_c = 0.5 * np.arctan2(2.0 * jxy_c, jxx_c - jyy_c)
        trace_r = jxx_r + jyy_r
        coh_energy = np.sqrt((jxx_r - jyy_r) ** 2 + 4.0 * (jxy_r ** 2))
        aniso_r = coh_energy / (trace_r + 1e-6)

        mask = (trace_r > 10.0) & (aniso_r > 0.15)
        if not np.any(mask):
            mask = np.ones_like(trace_r, dtype=bool)
        cos2_diff = np.cos(2.0 * (theta_c[mask] - theta_r[mask]))
        weights = coh_energy[mask]
        w_sum = float(np.sum(weights))
        if w_sum > 1e-9:
            orient_coh = float(np.sum(weights * cos2_diff) / w_sum)
        else:
            orient_coh = float(np.mean(cos2_diff))

        # 2D FFT periodicity coherence (exclude DC/very-low-frequency envelope r_px < 2)
        yr_zm = yr - float(np.mean(yr))
        yc_zm = yc - float(np.mean(yc))
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

        roi_ok = orient_coh >= 0.80 and fft_coh >= 0.75 and energy_ratio >= 0.90
        if not roi_ok:
            fabric_passed = False

        fabric_reports.append(
            {
                "id": r["id"],
                "rect": r["rect"],
                "weave_orientation_coherence": round(orient_coh, 6),
                "weave_fft_coherence": round(fft_coh, 6),
                "weave_energy_ratio": round(energy_ratio, 6),
                "passed": bool(roi_ok),
            }
        )

    # 2. Hardware & seam zero-drift / zero-overshoot
    hw_seam_rois = [r for r in norm_rois if r["kind"] in _HW_SEAM_ROI_KINDS]
    hw_seam_reports: list[dict[str, Any]] = []
    hw_seam_passed = True
    locked_mismatches = 0

    if hw_seam_rois:
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
        locked_mismatches = int(drift_res["locked_pixel_mismatches"])
        if locked_mismatches > 0:
            hw_seam_passed = False
    elif protected is not None:
        prot_arr = np.asarray(protected, dtype=np.float32)
        if prot_arr.shape[:2] == (h, w):
            locked_pixels = prot_arr == 1.0
            if np.any(locked_pixels):
                check_rgb = (
                    master_rgb
                    if (master_rgb is not None and not np.array_equal(master_rgb, bicubic_rgb))
                    else candidate_rgb
                )
                locked_mismatches = int(
                    np.sum(np.any(check_rgb[locked_pixels] != bicubic_rgb[locked_pixels], axis=-1))
                )
                if locked_mismatches > 0:
                    hw_seam_passed = False

    if hw_seam_rois:

        kernel5 = np.ones((5, 5), np.uint8)
        local_max_ref = cv2.dilate(y_bic, kernel5)
        local_min_ref = cv2.erode(y_bic, kernel5)

        for r, drep in zip(hw_seam_rois, drift_res["roi_reports"]):
            rx, ry, rw, rh = r["rect"]
            yc_roi = y_cand[ry:ry + rh, rx:rx + rw]
            lmax_roi = local_max_ref[ry:ry + rh, rx:rx + rw]
            lmin_roi = local_min_ref[ry:ry + rh, rx:rx + rw]

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
            if not roi_ok:
                hw_seam_passed = False

            hw_seam_reports.append(
                {
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
            )

    return {
        "fabric_rois_evaluated": len(fabric_reports),
        "fabric_weave_passed": bool(fabric_passed),
        "fabric_reports": fabric_reports,
        "hardware_seam_rois_evaluated": len(hw_seam_reports),
        "hardware_seam_passed": bool(hw_seam_passed),
        "locked_pixel_mismatches": locked_mismatches,
        "hardware_seam_reports": hw_seam_reports,
        "passed": bool(fabric_passed and hw_seam_passed),
    }


def measure_scale_matched_metrics(
    candidate_bgr: Optional[np.ndarray],
    bicubic_bgr: Optional[np.ndarray],
    source_bgr: Optional[np.ndarray] = None,
    *,
    rois: Optional[Sequence[Mapping[str, Any]]] = None,
    roi_space: str = "auto",
    protected: Optional[np.ndarray] = None,
    master_bgr: Optional[np.ndarray] = None,
    input_color_order: str = "bgr",
) -> dict[str, Any]:
    """Compute F2, F3, and F4 scale-matched native-4x metrics against a bicubic reference."""
    if candidate_bgr is None or bicubic_bgr is None:
        return {
            "schema_version": 1,
            "status": "unavailable",
            "reason": "candidate_or_bicubic_missing",
            "interior_texture_passed": None,
            "oversharpen_restraint_passed": None,
            "fabric_weave_passed": None,
            "hardware_seam_passed": None,
            "all_detail_gates_passed": False,
        }

    if candidate_bgr.ndim != 3 or bicubic_bgr.ndim != 3 or candidate_bgr.shape[2] != 3 or bicubic_bgr.shape[2] != 3:
        return {
            "schema_version": 1,
            "status": "unavailable",
            "reason": "invalid_image_channels",
            "interior_texture_passed": None,
            "oversharpen_restraint_passed": None,
            "fabric_weave_passed": None,
            "hardware_seam_passed": None,
            "all_detail_gates_passed": False,
        }

    if candidate_bgr.shape[0] <= 0 or candidate_bgr.shape[1] <= 0 or bicubic_bgr.shape[0] <= 0 or bicubic_bgr.shape[1] <= 0:
        return {
            "schema_version": 1,
            "status": "unavailable",
            "reason": "empty_image_dimensions",
            "interior_texture_passed": None,
            "oversharpen_restraint_passed": None,
            "fabric_weave_passed": None,
            "hardware_seam_passed": None,
            "all_detail_gates_passed": False,
        }

    if (
        not np.all(np.isfinite(candidate_bgr))
        or not np.all(np.isfinite(bicubic_bgr))
        or (master_bgr is not None and not np.all(np.isfinite(master_bgr)))
    ):
        return {
            "schema_version": 1,
            "status": "unavailable",
            "reason": "nonfinite_input",
            "interior_texture_passed": None,
            "oversharpen_restraint_passed": None,
            "fabric_weave_passed": None,
            "hardware_seam_passed": None,
            "all_detail_gates_passed": False,
        }

    if candidate_bgr.shape[:2] != bicubic_bgr.shape[:2]:
        return {
            "schema_version": 1,
            "status": "unavailable",
            "reason": "dimension_mismatch_silent_resizing_forbidden",
            "candidate_dimensions": [int(candidate_bgr.shape[1]), int(candidate_bgr.shape[0])],
            "bicubic_dimensions": [int(bicubic_bgr.shape[1]), int(bicubic_bgr.shape[0])],
            "interior_texture_passed": None,
            "oversharpen_restraint_passed": None,
            "fabric_weave_passed": None,
            "hardware_seam_passed": None,
            "all_detail_gates_passed": False,
        }

    if input_color_order.lower() == "bgr":
        cand_rgb = np.ascontiguousarray(candidate_bgr[:, :, ::-1])
        bic_rgb = np.ascontiguousarray(bicubic_bgr[:, :, ::-1])
        master_rgb = np.ascontiguousarray(master_bgr[:, :, ::-1]) if master_bgr is not None else None
    elif input_color_order.lower() == "rgb":
        cand_rgb = candidate_bgr
        bic_rgb = bicubic_bgr
        master_rgb = master_bgr
    else:
        raise ValueError(f"Unsupported input_color_order {input_color_order!r}")

    th, tw = cand_rgb.shape[:2]
    src_shape = (int(source_bgr.shape[0]), int(source_bgr.shape[1])) if source_bgr is not None and source_bgr.ndim >= 2 else None
    scaled_rois = _normalize_rois_to_target(rois, (th, tw), source_shape=src_shape, roi_space=roi_space)

    f2 = measure_interior_texture_retention(cand_rgb, bic_rgb, rois=scaled_rois)
    f3 = measure_oversharpening_restraint(cand_rgb, bic_rgb, rois=scaled_rois)
    f4 = measure_fabric_hardware_faithfulness(
        cand_rgb,
        bic_rgb,
        rois=scaled_rois,
        protected=protected,
        master_rgb=master_rgb,
    )

    all_passed = bool(
        f2["passed"]
        and f3["passed"]
        and f4["fabric_weave_passed"]
        and f4["hardware_seam_passed"]
    )

    return {
        "schema_version": 1,
        "status": "measured",
        "native_dimensions": [int(tw), int(th)],
        "interior_texture": f2,
        "oversharpening_restraint": f3,
        "fabric_hardware": f4,
        "interior_texture_passed": bool(f2["passed"]),
        "oversharpen_restraint_passed": bool(f3["passed"]),
        "fabric_weave_passed": bool(f4["fabric_weave_passed"]),
        "hardware_seam_passed": bool(f4["hardware_seam_passed"]),
        "all_detail_gates_passed": all_passed,
    }
