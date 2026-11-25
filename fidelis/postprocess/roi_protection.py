"""Structural ROI protection routing and internal geometric drift screening (F10 / MEL-64).

Explicit protection overrides and manual locks always win. Secondary Sobel
edge attenuation and local patch correlation screen spatial mismatch; neither
is semantic identity proof or OCR perfection.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from math import isfinite
from numbers import Integral, Real
from typing import Any

import numpy as np
from scipy import ndimage

from fidelis.postprocess.regions import _mask, _rgb

VALID_ROI_KINDS = (
    "skin",
    "hair",
    "fabric",
    "crema",
    "texture",
    "logo",
    "text",
    "seam",
    "hardware",
    "background",
    "highlight",
    "shadow",
    "identity",
    "alpha_boundary",
)
HARD_CONTOUR_ROI_KINDS = (
    "hardware",
    "seam",
    "logo",
    "text",
    "identity",
    "alpha_boundary",
)
INTERIOR_TEXTURE_ROI_KINDS = (
    "skin",
    "hair",
    "fabric",
    "crema",
    "texture",
)
VALID_POLICIES = ("preserve", "texture_allowed")
VALID_OVERRIDES = (None, "lock", "unlock")


def classify_roi_role(kind: str) -> str:
    """Classify an ROI kind into 'hard_contour', 'interior_texture', or 'other'."""
    if kind in HARD_CONTOUR_ROI_KINDS:
        return "hard_contour"
    if kind in INTERIOR_TEXTURE_ROI_KINDS:
        return "interior_texture"
    return "other"


def _luminance(rgb: np.ndarray) -> np.ndarray:
    arr = rgb.astype(np.float32, copy=False)
    return 0.2126 * arr[:, :, 0] + 0.7152 * arr[:, :, 1] + 0.0722 * arr[:, :, 2]


class RoiValidationError(ValueError, TypeError):
    """Raised when ROI declaration is structurally invalid or has wrong types."""


def _validate_rectangle(rect, rid, width, height):
    if (
        not isinstance(rect, (list, tuple))
        or len(rect) != 4
        or any(isinstance(v, bool) or not isinstance(v, int) for v in rect)
    ):
        raise ValueError(f"ROI {rid}: rect must contain four integers [x, y, w, h]")
    x, y, w, h = rect
    if x < 0 or y < 0 or w < 1 or h < 1 or x + w > width or y + h > height:
        raise ValueError(f"ROI {rid}: rect {list(rect)} out of image bounds {width}x{height}")
    return [x, y, w, h]


def _validate_roi_choices(entry, rid):
    choices = {"kind": VALID_ROI_KINDS, "policy": VALID_POLICIES, "override": VALID_OVERRIDES}
    result = {}
    for key, allowed in choices.items():
        value = entry.get(key)
        if value not in allowed:
            raise ValueError(f"ROI {rid}: invalid {key} {value!r}")
        result[key] = value
    return result


def validate_rois(
    rois: Sequence[dict[str, Any]],
    shape: tuple[int, int],
) -> list[dict[str, Any]]:
    """Validate explicit ROI declarations against image (height, width)."""
    if not isinstance(rois, (list, tuple)):
        raise RoiValidationError("rois must be a sequence of ROI dictionaries")
    height, width = int(shape[0]), int(shape[1])
    if height <= 0 or width <= 0:
        raise ValueError("shape dimensions must be positive integers")

    seen_ids = set()
    normalized: list[dict[str, Any]] = []
    for entry in rois:
        if not isinstance(entry, dict):
            raise RoiValidationError("Each ROI entry must be a JSON/dict object")
        rid = entry.get("id")
        if not isinstance(rid, str) or not rid.strip() or rid in seen_ids:
            raise ValueError(f"Missing, empty, or duplicate ROI id: {rid!r}")
        seen_ids.add(rid)

        normalized.append(
            {
                "id": rid,
                **_validate_roi_choices(entry, rid),
                "rect": _validate_rectangle(entry.get("rect"), rid, width, height),
                "label": str(entry.get("label", rid)),
            }
        )
    return normalized


def _roi_lock_masks(norm_rois, shape):
    roi_locked = np.zeros(shape, dtype=np.float32)
    explicit_unlock = np.zeros(shape, dtype=bool)
    locked_ids: list[str] = []
    unlocked_override_ids: list[str] = []
    forced_lock_ids: list[str] = []

    for roi in norm_rois:
        x, y, w, h = roi["rect"]
        if roi["policy"] == "preserve" and roi["override"] is None:
            roi_locked[y:y + h, x:x + w] = 1.0

    for roi in norm_rois:
        x, y, w, h = roi["rect"]
        if roi["override"] == "unlock":
            roi_locked[y:y + h, x:x + w] = 0.0
            explicit_unlock[y:y + h, x:x + w] = True
            unlocked_override_ids.append(roi["id"])

    for roi in norm_rois:
        x, y, w, h = roi["rect"]
        if roi["override"] == "lock":
            roi_locked[y:y + h, x:x + w] = 1.0
            explicit_unlock[y:y + h, x:x + w] = False
            forced_lock_ids.append(roi["id"])

    for roi in norm_rois:
        x, y, w, h = roi["rect"]
        if (
            (roi["policy"] == "preserve" and roi["override"] is None) or roi["override"] == "lock"
        ) and np.any(roi_locked[y:y + h, x:x + w] == 1.0):
            locked_ids.append(roi["id"])
    return roi_locked, explicit_unlock, locked_ids, unlocked_override_ids, forced_lock_ids


def _roi_semantic_masks(norm_rois, roi_locked, explicit_unlock):
    shape = roi_locked.shape
    hard_contour_bool = roi_locked == 1.0
    for roi in norm_rois:
        if roi["kind"] in HARD_CONTOUR_ROI_KINDS and roi["override"] != "unlock":
            x, y, w, h = roi["rect"]
            hard_contour_bool[y:y + h, x:x + w] = True
    hard_contour_bool &= ~explicit_unlock
    hard_contour = hard_contour_bool.astype(np.float32)

    interior_texture_bool = np.zeros(shape, dtype=bool)
    for roi in norm_rois:
        if (
            roi["kind"] in INTERIOR_TEXTURE_ROI_KINDS
            and roi["policy"] == "texture_allowed"
            and roi["override"] != "lock"
        ):
            x, y, w, h = roi["rect"]
            interior_texture_bool[y:y + h, x:x + w] = True
    interior_texture_bool &= ~hard_contour_bool
    interior_texture = interior_texture_bool.astype(np.float32)
    return hard_contour, interior_texture, interior_texture_bool


_DRIFT_STRIP_ROWS = 256


def _roi_edge_guard(base_rgb, user_edge_guard, use_sobel_heuristic, sobel_strength, max_sobel_guard, suppress):
    edge_guard = np.array(user_edge_guard, dtype=np.float32, copy=True)
    if not use_sobel_heuristic:
        return edge_guard
    height, width = base_rgb.shape[:2]
    mag = np.empty((height, width), dtype=np.float32)
    for y0 in range(0, height, _DRIFT_STRIP_ROWS):
        y1 = min(height, y0 + _DRIFT_STRIP_ROWS)
        sy0 = max(0, y0 - 1)
        sy1 = min(height, y1 + 1)
        lum_s = _luminance(base_rgb[sy0:sy1])
        gx_s = ndimage.sobel(lum_s, axis=1)
        gy_s = ndimage.sobel(lum_s, axis=0)
        mag_s = np.sqrt(gx_s * gx_s + gy_s * gy_s)
        mag[y0:y1] = mag_s[y0 - sy0:y1 - sy0]
    ref_scale = max(float(np.percentile(mag, 95)), 25.0)
    strength = float(sobel_strength)
    max_guard = float(max_sobel_guard)
    for y0 in range(0, height, _DRIFT_STRIP_ROWS):
        y1 = min(height, y0 + _DRIFT_STRIP_ROWS)
        strip = np.clip((mag[y0:y1] / ref_scale) * strength, 0.0, max_guard).astype(np.float32)
        strip[suppress[y0:y1]] = 0.0
        np.maximum(edge_guard[y0:y1], strip, out=edge_guard[y0:y1])
    return edge_guard


def _roi_metadata(norm_rois, roi_locked):
    hard_contour_roi_ids: list[str] = []
    interior_texture_roi_ids: list[str] = []
    texture_allowed_roi_ids: list[str] = []
    roi_summary: list[dict[str, Any]] = []
    for roi in norm_rois:
        x, y, w, h = roi["rect"]
        role = classify_roi_role(roi["kind"])
        if role == "hard_contour":
            hard_contour_roi_ids.append(roi["id"])
        elif role == "interior_texture":
            interior_texture_roi_ids.append(roi["id"])
        if roi["policy"] == "texture_allowed":
            texture_allowed_roi_ids.append(roi["id"])
        roi_summary.append(
            {
                "id": roi["id"],
                "kind": roi["kind"],
                "role": role,
                "policy": roi["policy"],
                "override": roi["override"],
                "effective_locked": bool(np.any(roi_locked[y:y + h, x:x + w] == 1.0)),
                "rect": roi["rect"],
            }
        )
    return hard_contour_roi_ids, interior_texture_roi_ids, texture_allowed_roi_ids, roi_summary


def build_roi_protection_masks(
    base: np.ndarray,
    rois: Sequence[dict[str, Any]],
    *,
    existing_protected: np.ndarray | None = None,
    existing_edge_guard: np.ndarray | None = None,
    use_sobel_heuristic: bool = False,
    sobel_strength: float = 0.35,
    max_sobel_guard: float = 0.65,
) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    """Build explicit ROI protection masks while preserving override precedence.

    Precedence order:
    1. Manifest/default `policy == 'preserve'` locks ROI pixels in `protected`.
    2. Explicit `override == 'unlock'` clears ROI/heuristic protection for that box.
    3. Explicit `override == 'lock'` locks the box even if `policy == 'texture_allowed'`.
    4. Caller-supplied `existing_protected` is preserved monotonically (never weakened).
    """
    base_rgb = _rgb(base, "base")
    shape = base_rgb.shape[:2]
    height, width = shape
    norm_rois = validate_rois(rois, shape)

    user_protected = _mask(existing_protected, shape, "existing_protected")
    user_edge_guard = _mask(existing_edge_guard, shape, "existing_edge_guard")

    if not 0.0 <= float(sobel_strength) <= 1.0:
        raise ValueError("sobel_strength must be in [0, 1]")
    if not 0.0 <= float(max_sobel_guard) < 1.0:
        raise ValueError("max_sobel_guard must be in [0, 1) (heuristic never replaces explicit locks)")

    roi_locked, explicit_unlock, locked_ids, unlocked_override_ids, forced_lock_ids = _roi_lock_masks(norm_rois, shape)
    protected = np.maximum(user_protected, roi_locked).astype(np.float32)

    hard_contour, interior_texture, interior_texture_bool = _roi_semantic_masks(norm_rois, roi_locked, explicit_unlock)
    edge_guard = _roi_edge_guard(
        base_rgb, user_edge_guard, use_sobel_heuristic, sobel_strength, max_sobel_guard,
        explicit_unlock | (interior_texture == 1.0),
    )
    hard_contour_roi_ids, interior_texture_roi_ids, texture_allowed_roi_ids, roi_summary = _roi_metadata(norm_rois, roi_locked)

    receipt = {
        "schema_version": 1,
        "dimensions": [width, height],
        "roi_count": len(norm_rois),
        "locked_roi_ids": locked_ids,
        "forced_lock_override_ids": forced_lock_ids,
        "unlocked_override_ids": unlocked_override_ids,
        "locked_fraction": round(float(np.mean(protected == 1.0)), 6),
        "sobel_heuristic_enabled": bool(use_sobel_heuristic),
        "sobel_is_semantic_proof": False,
        "sobel_notice": (
            "Sobel luminance gradient is a contrast heuristic only (it also fires on skin "
            "pores/fabric weave and misses low-contrast hardware); it is not semantic proof."
        ),
        "hard_contour_roi_ids": hard_contour_roi_ids,
        "interior_texture_roi_ids": interior_texture_roi_ids,
        "texture_allowed_roi_ids": texture_allowed_roi_ids,
        "hard_contour_fraction": round(float(np.mean(hard_contour == 1.0)), 6),
        "interior_texture_fraction": round(float(np.mean(interior_texture == 1.0)), 6),
        "sobel_suppressed_in_interior_texture": bool(use_sobel_heuristic and np.any(interior_texture_bool)),
        "roi_summary": roi_summary,
    }
    return {
        "protected": protected,
        "edge_guard": edge_guard,
        "hard_contour": hard_contour,
        "interior_texture": interior_texture,
    }, receipt


def _estimate_patch_shift(
    ref_lum: np.ndarray,
    cand_lum: np.ndarray,
    y0: int,
    x0: int,
    y1: int,
    x1: int,
    search_radius: int,
) -> tuple[int, int, float]:
    """Estimate local integer translation (dx, dy) via zero-mean patch SSD inside reference bounds."""
    height, width = ref_lum.shape
    patch_r = ref_lum[y0:y1, x0:x1]
    pr_zm = patch_r - float(np.mean(patch_r))
    c0 = cand_lum[y0:y1, x0:x1]
    ssd_zero = float(np.mean((pr_zm - (c0 - float(np.mean(c0)))) ** 2))

    # Avoid matching noise on flat regions.
    if float(np.var(pr_zm)) < 18.0:
        return 0, 0, 0.0

    best_dx, best_dy = 0, 0
    best_ssd = ssd_zero
    ph, pw = y1 - y0, x1 - x0

    # Visit only in-grid translations, in the original dy/dx order. A huge
    # radius must not spend time iterating over impossible translations.
    for dy in range(max(-search_radius, -y0), min(search_radius, height - y1) + 1):
        cy0 = y0 + dy
        cy1 = cy0 + ph
        for dx in range(max(-search_radius, -x0), min(search_radius, width - x1) + 1):
            if dx == 0 and dy == 0:
                continue
            cx0 = x0 + dx
            cx1 = cx0 + pw
            patch_c = cand_lum[cy0:cy1, cx0:cx1]
            pc_zm = patch_c - float(np.mean(patch_c))
            ssd = float(np.mean((pr_zm - pc_zm) ** 2))
            if ssd < best_ssd:
                best_ssd = ssd
                best_dx, best_dy = dx, dy

    # Only report displacement when shifted patch materially improves zero-mean match (>= 20% SSD drop).
    if best_ssd > ssd_zero * 0.80 or (ssd_zero - best_ssd) < 4.0:
        return 0, 0, 0.0
    improvement = 1.0 - (best_ssd / max(ssd_zero, 1e-6))
    return best_dx, best_dy, float(improvement)


def _gradient_coherence(
    gx_r: np.ndarray,
    gy_r: np.ndarray,
    mag_r: np.ndarray,
    gx_c: np.ndarray,
    gy_c: np.ndarray,
    mag_c: np.ndarray,
) -> float | None:
    edge_mask = mag_r > 15.0
    if not np.any(edge_mask):
        return None
    dot = gx_r[edge_mask] * gx_c[edge_mask] + gy_r[edge_mask] * gy_c[edge_mask]
    denom = mag_r[edge_mask] * mag_c[edge_mask] + 1e-6
    return float(np.mean(np.clip(dot / denom, 0.0, 1.0)))


@dataclass(frozen=True)
class _DriftSettings:
    block_size: int
    search_radius: int
    shift_warn_px: float
    shift_fail_px: float
    min_edge_coherence: float

    def __post_init__(self):
        _validate_integer(self.block_size, 8, "block_size")
        _validate_integer(self.search_radius, 1, "search_radius")
        _validate_threshold(self.shift_warn_px, "shift_warn_px")
        _validate_threshold(self.shift_fail_px, "shift_fail_px")
        _validate_threshold(self.min_edge_coherence, "min_edge_coherence")
        if not 0 <= self.shift_warn_px <= self.shift_fail_px:
            raise ValueError("Shift thresholds require 0 <= warning <= failure")
        if not 0 <= self.min_edge_coherence <= 1:
            raise ValueError("min_edge_coherence must be in [0, 1]")


def _validate_integer(value, minimum, name):
    if isinstance(value, bool) or not isinstance(value, Integral) or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")


def _validate_threshold(value, name):
    if isinstance(value, bool) or not isinstance(value, Real) or not isfinite(value):
        raise ValueError(f"{name} must be a finite real number")


def _gradients(luminance):
    gx = ndimage.sobel(luminance, axis=1)
    gy = ndimage.sobel(luminance, axis=0)
    return gx, gy, np.sqrt(gx * gx + gy * gy)


@dataclass(frozen=True)
class _DriftImages:
    base: np.ndarray
    candidate: np.ndarray
    master: np.ndarray | None
    protected: np.ndarray | None

    def make_window(self, y0: int, x0: int, y1: int, x1: int, search_radius: int):
        height, width = self.base.shape[:2]
        pad = search_radius + 1
        sy0 = max(0, y0 - pad)
        sy1 = min(height, y1 + pad)
        sx0 = max(0, x0 - pad)
        sx1 = min(width, x1 + pad)
        ref_lum = _luminance(self.base[sy0:sy1, sx0:sx1])
        cand_lum = _luminance(self.candidate[sy0:sy1, sx0:sx1])
        return _DriftWindow(
            ref_lum=ref_lum,
            cand_lum=cand_lum,
            ref_grads=_gradients(ref_lum),
            cand_grads=_gradients(cand_lum),
            y_offset=sy0,
            x_offset=sx0,
        )


@dataclass(frozen=True)
class _DriftWindow:
    ref_lum: np.ndarray
    cand_lum: np.ndarray
    ref_grads: tuple
    cand_grads: tuple
    y_offset: int
    x_offset: int

    def measure(self, rectangle, search_radius):
        y0, x0, y1, x1 = rectangle
        ry0, ry1 = y0 - self.y_offset, y1 - self.y_offset
        rx0, rx1 = x0 - self.x_offset, x1 - self.x_offset
        dx, dy, improvement = _estimate_patch_shift(
            self.ref_lum, self.cand_lum, ry0, rx0, ry1, rx1, search_radius
        )
        area = np.s_[ry0:ry1, rx0:rx1]
        coherence = _gradient_coherence(
            *(gradient[area] for gradient in self.ref_grads + self.cand_grads)
        )
        return dx, dy, improvement, coherence


def _drift_roi_maps(rois, shape):
    locked = np.zeros(shape, dtype=bool)
    texture_allowed = np.zeros(shape, dtype=bool)
    for roi in rois:
        x, y, w, h = roi["rect"]
        area = np.s_[y:y + h, x:x + w]
        if roi["policy"] == "preserve" and roi["override"] is None:
            locked[area] = True
        elif roi["policy"] == "texture_allowed" and roi["override"] != "lock":
            texture_allowed[area] = True
    for override, lock in (("unlock", False), ("lock", True)):
        for roi in rois:
            if roi["override"] == override:
                x, y, w, h = roi["rect"]
                locked[y:y + h, x:x + w] = lock
                texture_allowed[y:y + h, x:x + w] = not lock
    return locked, texture_allowed


def _coherence_flag(images, texture_allowed, area, coherence, minimum):
    if coherence is None or coherence >= minimum or np.any(texture_allowed[area]):
        return False
    unlocked = images.protected is not None and not np.any(images.protected[area] == 1.0)
    return not (images.master is not None and unlocked)


def _screen_blocks(images, texture_allowed, settings):
    height, width = images.base.shape[:2]
    guard = np.zeros((height, width), dtype=np.float32)
    step = min(settings.block_size, height, width)
    evaluated = flagged = 0
    max_shift = 0.0
    coherence_values = []
    for y0 in range(0, height, step):
        y1 = min(height, y0 + step)
        if y1 - y0 < 3:
            continue
        window = images.make_window(y0, 0, y1, width, settings.search_radius)
        for x0 in range(0, width, step):
            x1 = min(width, x0 + step)
            if x1 - x0 < 3:
                continue
            area = np.s_[y0:y1, x0:x1]
            dx, dy, _, coherence = window.measure((y0, x0, y1, x1), settings.search_radius)
            shift = float(np.hypot(dx, dy))
            evaluated += 1
            if coherence is not None:
                coherence_values.append(coherence)
            max_shift = max(max_shift, shift)
            if shift >= settings.shift_warn_px or _coherence_flag(
                images, texture_allowed, area, coherence, settings.min_edge_coherence
            ):
                flagged += 1
                severe = shift >= settings.shift_fail_px or (
                    coherence is not None and coherence < settings.min_edge_coherence - 0.15
                )
                guard[area] = max(float(guard[area].max()), 1.0 if severe else 0.6)
    return {
        "blocks_evaluated": evaluated, "blocks_flagged": flagged,
        "max_block_shift_px": max_shift,
        "min_block_coherence": round(min(coherence_values), 4) if coherence_values else None,
        "drift_guard_mask": guard,
    }


def _locked_mismatches(images):
    if images.master is None or images.protected is None:
        return 0
    height = images.base.shape[0]
    mismatches = 0
    for y0 in range(0, height, _DRIFT_STRIP_ROWS):
        y1 = min(height, y0 + _DRIFT_STRIP_ROWS)
        locked = images.protected[y0:y1] == 1.0
        if np.any(locked):
            mismatches += int(np.sum(np.any(images.master[y0:y1][locked] != images.base[y0:y1][locked], axis=-1)))
    return mismatches


def _roi_status(expected_locked, master_diff, shift, coherence, texture_allowed, settings):
    if expected_locked and master_diff is not None and master_diff > 0:
        return "LOCK_VIOLATION"
    check_coherence = coherence is not None and not texture_allowed
    if shift >= settings.shift_fail_px or (check_coherence and coherence < settings.min_edge_coherence - 0.12):
        return "FAIL_DRIFT"
    if shift >= settings.shift_warn_px or (check_coherence and coherence < settings.min_edge_coherence):
        return "WARN_DRIFT"
    return "LOCKED_EXACT" if expected_locked and master_diff == 0 else "PASS"


def _screen_roi(images, roi, roi_locked, settings):
    x, y, w, h = roi["rect"]
    area = np.s_[y:y + h, x:x + w]
    window = images.make_window(y, x, y + h, x + w, settings.search_radius)
    dx, dy, improvement, coherence = window.measure((y, x, y + h, x + w), settings.search_radius)
    shift = round(float(np.hypot(dx, dy)), 3)
    base = images.base[area].astype(np.int16)
    candidate_diff = np.abs(images.candidate[area].astype(np.int16) - base)
    locked = roi_locked[area]
    expected_locked = bool(np.any(locked))
    master_diff = None
    if images.master is not None:
        diff = np.abs(images.master[area].astype(np.int16) - base)
        master_diff = int(diff[locked].max()) if expected_locked else int(diff.max())
    texture_allowed = (
        roi["policy"] == "texture_allowed" and roi["override"] != "lock"
    ) or roi["override"] == "unlock"
    status = _roi_status(expected_locked, master_diff, shift, coherence, texture_allowed, settings)
    return {
        "id": roi["id"], "kind": roi["kind"], "role": classify_roi_role(roi["kind"]),
        "policy": roi["policy"], "override": roi["override"], "rect": roi["rect"],
        "expected_locked": expected_locked, "status": status, "candidate_shift_px": shift,
        "candidate_shift_vec": [dx, dy], "candidate_shift_improvement": round(improvement, 3),
        "candidate_edge_coherence": round(coherence, 4) if coherence is not None else None,
        "candidate_max_abs_diff": int(candidate_diff.max()),
        "candidate_mean_abs_diff": round(float(candidate_diff.mean()), 3),
        "master_max_abs_diff": master_diff,
    }


def _overall_verdict(blocks, roi_reports, mismatches, has_master, settings):
    statuses = {report["status"] for report in roi_reports}
    max_shift = blocks["max_block_shift_px"]
    if mismatches or max_shift >= settings.shift_fail_px or statuses & {"LOCK_VIOLATION", "FAIL_DRIFT"}:
        return "FAIL"
    if max_shift >= settings.shift_warn_px or "WARN_DRIFT" in statuses:
        return "WARN"
    if blocks["blocks_flagged"] > 0 and not has_master:
        return "WARN"
    return "PASS"


def screen_internal_drift(
    base: np.ndarray,
    candidate: np.ndarray,
    *,
    rois: Sequence[dict[str, Any]] = (),
    protected: np.ndarray | None = None,
    master: np.ndarray | None = None,
    block_size: int = 32,
    search_radius: int = 4,
    shift_warn_px: float = 1.5,
    shift_fail_px: float = 2.5,
    min_edge_coherence: float = 0.80,
) -> dict[str, Any]:
    """Screen aligned candidate/master passes for internal spatial drift and exact-lock violations."""
    settings = _DriftSettings(block_size, search_radius, shift_warn_px, shift_fail_px, min_edge_coherence)
    base_rgb = _rgb(base, "base")
    cand_rgb = _rgb(candidate, "candidate")
    if base_rgb.shape != cand_rgb.shape:
        raise ValueError(
            "base and candidate must have identical dimensions; equal dimensions never excuse internal drift"
        )
    height, width = base_rgb.shape[:2]
    shape = (height, width)
    master_rgb = _rgb(master, "master") if master is not None else None
    if master_rgb is not None and master_rgb.shape != base_rgb.shape:
        raise ValueError("master must have identical dimensions to base")

    prot_mask = _mask(protected, shape, "protected") if protected is not None else None
    norm_rois = validate_rois(rois, shape)
    images = _DriftImages(base_rgb, cand_rgb, master_rgb, prot_mask)
    locked, texture_allowed = _drift_roi_maps(norm_rois, shape)
    blocks = _screen_blocks(images, texture_allowed, settings)
    mismatches = _locked_mismatches(images)
    roi_reports = [_screen_roi(images, roi, locked, settings) for roi in norm_rois]
    verdict = _overall_verdict(blocks, roi_reports, mismatches, master_rgb is not None, settings)
    blocks["max_block_shift_px"] = round(blocks["max_block_shift_px"], 3)
    return {
        "schema_version": 1,
        "dimensions": [width, height],
        "overall_verdict": verdict,
        **blocks,
        "locked_pixel_mismatches": mismatches,
        "roi_reports": roi_reports,
        "semantic_proof": False,
        "heuristic_limitations": [
            "Block correlation and Sobel edge coherence detect geometric/gradient mismatch only.",
            "They do not verify OCR readability, facial identity equivalence, or semantic object realism.",
        ],
    }
