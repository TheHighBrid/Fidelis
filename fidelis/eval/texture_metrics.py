"""Native-grid texture retention and contour restraint metrics."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import cv2
import numpy as np

from fidelis.eval.roi_normalization import normalize_rois_to_target as _normalize_rois_to_target

_TEXTURE_ROI_KINDS = frozenset({"fabric", "crema", "skin", "hair"})
_CONTOUR_ROI_KINDS = frozenset({"hardware", "seam", "logo", "text"})
_SPECTRAL_MEMORY_THRESHOLD = 4_000_000


def _bt709_luminance(rgb: np.ndarray) -> np.ndarray:
    # Preserve float32 arithmetic without a full-frame RGB float32 temporary.
    out = np.empty(rgb.shape[:2], dtype=np.float32)
    for y in range(0, rgb.shape[0], 128):
        arr = rgb[y:y + 128].astype(np.float32)
        out[y:y + 128] = 0.2126 * arr[:, :, 0] + 0.7152 * arr[:, :, 1] + 0.0722 * arr[:, :, 2]
    return out


def _radial_frequency_grid(height: int, width: int) -> np.ndarray:
    fy = np.fft.fftshift(np.fft.fftfreq(height))
    fx = np.fft.fftshift(np.fft.fftfreq(width))
    return np.sqrt(fy[:, None] ** 2 + fx[None, :] ** 2)


def _fft_power_spectrum(signal: np.ndarray) -> np.ndarray:
    h, w = signal.shape
    win = np.outer(np.hanning(h), np.hanning(w)).astype(np.float32)
    spec = np.fft.fftshift(np.fft.fft2(signal * win))
    return (np.abs(spec) ** 2) / max(float(h * w), 1.0)


def _spectral_band_means(signal, bands):
    if signal.size > _SPECTRAL_MEMORY_THRESHOLD:
        from fidelis.eval.spectral_memory import spectral_band_means
        return spectral_band_means(signal, bands)
    power = _fft_power_spectrum(signal)
    radius = _radial_frequency_grid(*signal.shape)
    means = {}
    for name, (low, high, inclusive_low) in bands.items():
        mask = ((radius >= low) if inclusive_low else (radius > low)) & (radius <= high)
        means[name] = float(np.mean(power[mask])) if np.any(mask) else 0.0
    return means


def _highpass_statistics(y, mask, bands, *, variance=False):
    hp = y - cv2.GaussianBlur(y, (0, 0), sigmaX=2.0)
    samples = hp[mask]
    var = float(np.var(samples)) if variance else None
    mean = float(np.mean(samples))
    del samples
    # hp is private to this call, so these operations need no extra frame buffers.
    np.subtract(hp, mean, out=hp)
    np.multiply(hp, mask, out=hp)
    return var, _spectral_band_means(hp, bands)


def _texture_pool(y_bic, rois):
    h, w = y_bic.shape
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
    else:
        pool_mask = np.ones((h, w), dtype=bool)

    return mag_ref, pool_mask


def _texture_interior_mask(mag_ref, pool_mask):
    mag_pool = mag_ref[pool_mask]
    low_t = max(2.0, float(np.percentile(mag_pool, 25)))
    high_t = max(low_t + 1.0, float(np.percentile(mag_pool, 80)))
    interior_mask = pool_mask & (mag_ref >= low_t) & (mag_ref <= high_t)
    min_interior = min(64, max(1, int(pool_mask.sum()) // 2))
    if int(interior_mask.sum()) < min_interior:
        interior_mask = pool_mask

    return interior_mask


def _texture_ratios(y_cand, y_bic, interior_mask):
    bands = {"mid": (0.06, 0.25, True)}
    var_cand, candidate = _highpass_statistics(y_cand, interior_mask, bands, variance=True)
    var_bic, baseline = _highpass_statistics(y_bic, interior_mask, bands, variance=True)
    if var_bic < 1e-6 and var_cand < 1e-6:
        var_ratio = 1.0
    else:
        var_ratio = var_cand / max(var_bic, 1e-6)

    e_mid_cand, e_mid_bic = candidate["mid"], baseline["mid"]

    if e_mid_bic < 1e-9 and e_mid_cand < 1e-9:
        midband_ratio = 1.0
    else:
        midband_ratio = e_mid_cand / max(e_mid_bic, 1e-9)

    return var_ratio, midband_ratio


def _texture_unavailable(reason):
    return {
        "interior_texture_variance_ratio": 0.0,
        "interior_midband_energy_ratio": 0.0,
        "interior_pixel_count": 0,
        "passed": False,
        "reason": reason,
    }


def measure_interior_texture_retention(
    candidate_rgb: np.ndarray,
    bicubic_rgb: np.ndarray,
    *,
    rois: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """F2: Measure native 4x interior texture variance & mid-band spectral energy vs bicubic."""
    h, w = bicubic_rgb.shape[:2]
    if h <= 0 or w <= 0:
        return _texture_unavailable("empty_image_dimensions")
    if not np.all(np.isfinite(candidate_rgb)) or not np.all(np.isfinite(bicubic_rgb)):
        return _texture_unavailable("nonfinite_input")
    y_cand = _bt709_luminance(candidate_rgb)
    y_bic = _bt709_luminance(bicubic_rgb)

    mag_ref, pool_mask = _texture_pool(y_bic, rois)
    if not np.any(pool_mask):
        return _texture_unavailable("empty_texture_roi_pool")
    interior_mask = _texture_interior_mask(mag_ref, pool_mask)
    var_ratio, midband_ratio = _texture_ratios(y_cand, y_bic, interior_mask)
    passed = (var_ratio >= 1.0) and (midband_ratio >= 1.0)
    return {
        "interior_texture_variance_ratio": round(var_ratio, 6),
        "interior_midband_energy_ratio": round(midband_ratio, 6),
        "interior_pixel_count": int(interior_mask.sum()),
        "passed": bool(passed),
        "reason": None if passed else "texture_smoothed_below_bicubic",
    }


def _contour_band(y_bic, rois):
    h, w = y_bic.shape
    gx = cv2.Sobel(y_bic, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(y_bic, cv2.CV_32F, 0, 1, ksize=3)
    mag_ref = np.sqrt(gx * gx + gy * gy)

    norm_rois = _normalize_rois_to_target(rois, (h, w), roi_space="target")
    roi_mask: np.ndarray | None = None
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

    return contour_band


def _contour_excursion(y_cand, y_bic, contour_band):
    kernel5 = np.ones((5, 5), np.uint8)
    local_max = cv2.dilate(y_bic, kernel5)
    local_min = cv2.erode(y_bic, kernel5)
    excursion = np.maximum(0.0, y_cand - local_max) + np.maximum(0.0, local_min - y_cand)

    band_exc = excursion[contour_band]
    overshoot_mean = float(np.mean(band_exc))
    overshoot_p95 = float(np.percentile(band_exc, 95))
    overshoot_frac = float(np.mean(band_exc > 2.0))

    return overshoot_mean, overshoot_p95, overshoot_frac


def _contour_frequency(y_cand, y_bic, contour_band):
    bands = {"mid": (0.06, 0.25, True), "nyq": (0.25, 0.50, False)}
    _, candidate = _highpass_statistics(y_cand, contour_band, bands)
    _, baseline = _highpass_statistics(y_bic, contour_band, bands)
    e_nyq_c, e_mid_c = candidate["nyq"], candidate["mid"]
    e_nyq_b, e_mid_b = baseline["nyq"], baseline["mid"]

    ratio_c = e_nyq_c / max(e_mid_c, 1e-9)
    ratio_b = e_nyq_b / max(e_mid_b, 1e-9)
    if ratio_b < 1e-9 and ratio_c < 1e-9:
        nyquist_gain = 1.0
    else:
        nyquist_gain = ratio_c / max(ratio_b, 1e-9)

    return ratio_c, nyquist_gain


def _contour_unavailable(reason):
    return {
        "contour_overshoot_mean": 0.0,
        "contour_overshoot_p95": 0.0,
        "contour_overshoot_frac": 0.0,
        "contour_nyquist_to_midband_ratio": 0.0,
        "contour_nyquist_gain_vs_bicubic": 0.0,
        "contour_pixel_count": 0,
        "passed": False,
        "reason": reason,
    }


def measure_oversharpening_restraint(
    candidate_rgb: np.ndarray,
    bicubic_rgb: np.ndarray,
    *,
    rois: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """F3: Detect oversharpening halos, edge overshoot/undershoot, and Nyquist spikes."""
    h, w = bicubic_rgb.shape[:2]
    if h <= 0 or w <= 0:
        return _contour_unavailable("empty_image_dimensions")
    if not np.all(np.isfinite(candidate_rgb)) or not np.all(np.isfinite(bicubic_rgb)):
        return _contour_unavailable("nonfinite_input")
    y_cand = _bt709_luminance(candidate_rgb)
    y_bic = _bt709_luminance(bicubic_rgb)

    contour_band = _contour_band(y_bic, rois)
    overshoot_mean, overshoot_p95, overshoot_frac = _contour_excursion(y_cand, y_bic, contour_band)
    ratio_c, nyquist_gain = _contour_frequency(y_cand, y_bic, contour_band)
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
