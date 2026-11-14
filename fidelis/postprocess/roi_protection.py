"""Structural ROI protection routing and internal geometric drift screening (F10 / MEL-64).

Explicit protection overrides and manual locks always win. Secondary Sobel
edge attenuation and local patch correlation screen spatial mismatch; neither
is semantic identity proof or OCR perfection.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

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


def validate_rois(
    rois: Sequence[Dict[str, Any]],
    shape: Tuple[int, int],
) -> List[Dict[str, Any]]:
    """Validate explicit ROI declarations against image (height, width)."""
    if not isinstance(rois, (list, tuple)):
        raise ValueError("rois must be a sequence of ROI dictionaries")
    height, width = int(shape[0]), int(shape[1])
    if height <= 0 or width <= 0:
        raise ValueError("shape dimensions must be positive integers")

    seen_ids = set()
    normalized: List[Dict[str, Any]] = []
    for entry in rois:
        if not isinstance(entry, dict):
            raise ValueError("Each ROI entry must be a JSON/dict object")
        rid = entry.get("id")
        if not isinstance(rid, str) or not rid.strip() or rid in seen_ids:
            raise ValueError(f"Missing, empty, or duplicate ROI id: {rid!r}")
        seen_ids.add(rid)

        kind = entry.get("kind")
        if kind not in VALID_ROI_KINDS:
            raise ValueError(f"ROI {rid}: invalid kind {kind!r}")

        policy = entry.get("policy")
        if policy not in VALID_POLICIES:
            raise ValueError(f"ROI {rid}: invalid policy {policy!r}")

        override = entry.get("override")
        if override not in VALID_OVERRIDES:
            raise ValueError(f"ROI {rid}: invalid override {override!r}")

        rect = entry.get("rect")
        if (
            not isinstance(rect, (list, tuple))
            or len(rect) != 4
            or any(isinstance(v, bool) or not isinstance(v, int) for v in rect)
        ):
            raise ValueError(f"ROI {rid}: rect must contain four integers [x, y, w, h]")
        x, y, w, h = rect
        if x < 0 or y < 0 or w < 1 or h < 1 or x + w > width or y + h > height:
            raise ValueError(
                f"ROI {rid}: rect {list(rect)} out of image bounds {width}x{height}"
            )

        normalized.append(
            {
                "id": rid,
                "kind": kind,
                "policy": policy,
                "override": override,
                "rect": [x, y, w, h],
                "label": str(entry.get("label", rid)),
            }
        )
    return normalized


def build_roi_protection_masks(
    base: np.ndarray,
    rois: Sequence[Dict[str, Any]],
    *,
    existing_protected: Optional[np.ndarray] = None,
    existing_edge_guard: Optional[np.ndarray] = None,
    use_sobel_heuristic: bool = False,
    sobel_strength: float = 0.35,
    max_sobel_guard: float = 0.65,
) -> Tuple[Dict[str, np.ndarray], Dict[str, Any]]:
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

    roi_locked = np.zeros(shape, dtype=np.float32)
    explicit_unlock = np.zeros(shape, dtype=bool)
    locked_ids: List[str] = []
    unlocked_override_ids: List[str] = []
    forced_lock_ids: List[str] = []

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
        if (roi["policy"] == "preserve" and roi["override"] is None) or roi["override"] == "lock":
            if np.any(roi_locked[y:y + h, x:x + w] == 1.0):
                locked_ids.append(roi["id"])

    protected = np.maximum(user_protected, roi_locked).astype(np.float32)

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

    edge_guard = np.array(user_edge_guard, dtype=np.float32, copy=True)
    if use_sobel_heuristic:
        lum = _luminance(base_rgb)
        gx = ndimage.sobel(lum, axis=1)
        gy = ndimage.sobel(lum, axis=0)
        mag = np.sqrt(gx * gx + gy * gy)
        ref_scale = max(float(np.percentile(mag, 95)), 25.0)
        sobel_mask = np.clip((mag / ref_scale) * float(sobel_strength), 0.0, float(max_sobel_guard)).astype(np.float32)
        sobel_mask[explicit_unlock | (interior_texture == 1.0)] = 0.0
        edge_guard = np.maximum(edge_guard, sobel_mask).astype(np.float32)

    hard_contour_roi_ids: List[str] = []
    interior_texture_roi_ids: List[str] = []
    texture_allowed_roi_ids: List[str] = []
    roi_summary: List[Dict[str, Any]] = []
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
) -> Tuple[int, int, float]:
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

    for dy in range(-search_radius, search_radius + 1):
        cy0 = y0 + dy
        cy1 = cy0 + ph
        if cy0 < 0 or cy1 > height:
            continue
        for dx in range(-search_radius, search_radius + 1):
            if dx == 0 and dy == 0:
                continue
            cx0 = x0 + dx
            cx1 = cx0 + pw
            if cx0 < 0 or cx1 > width:
                continue
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
) -> Optional[float]:
    edge_mask = mag_r > 15.0
    if not np.any(edge_mask):
        return None
    dot = gx_r[edge_mask] * gx_c[edge_mask] + gy_r[edge_mask] * gy_c[edge_mask]
    denom = mag_r[edge_mask] * mag_c[edge_mask] + 1e-6
    return float(np.mean(np.clip(dot / denom, 0.0, 1.0)))


def screen_internal_drift(
    base: np.ndarray,
    candidate: np.ndarray,
    *,
    rois: Sequence[Dict[str, Any]] = (),
    protected: Optional[np.ndarray] = None,
    master: Optional[np.ndarray] = None,
    block_size: int = 32,
    search_radius: int = 4,
    shift_warn_px: float = 1.5,
    shift_fail_px: float = 2.5,
    min_edge_coherence: float = 0.80,
) -> Dict[str, Any]:
    """Screen aligned candidate/master passes for internal spatial drift and exact-lock violations."""
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

    if block_size < 8 or search_radius < 1:
        raise ValueError("block_size must be >= 8 and search_radius >= 1")

    ref_lum = _luminance(base_rgb)
    cand_lum = _luminance(cand_rgb)
    gx_r = ndimage.sobel(ref_lum, axis=1)
    gy_r = ndimage.sobel(ref_lum, axis=0)
    mag_r = np.sqrt(gx_r * gx_r + gy_r * gy_r)
    gx_c = ndimage.sobel(cand_lum, axis=1)
    gy_c = ndimage.sobel(cand_lum, axis=0)
    mag_c = np.sqrt(gx_c * gx_c + gy_c * gy_c)

    roi_lock_map = np.zeros((height, width), dtype=bool)
    texture_allowed_map = np.zeros((height, width), dtype=bool)
    for r in norm_rois:
        rx, ry, rw, rh = r["rect"]
        if r["policy"] == "preserve" and r["override"] is None:
            roi_lock_map[ry:ry + rh, rx:rx + rw] = True
        elif r["policy"] == "texture_allowed" and r["override"] != "lock":
            texture_allowed_map[ry:ry + rh, rx:rx + rw] = True
    for r in norm_rois:
        if r["override"] == "unlock":
            rx, ry, rw, rh = r["rect"]
            roi_lock_map[ry:ry + rh, rx:rx + rw] = False
            texture_allowed_map[ry:ry + rh, rx:rx + rw] = True
    for r in norm_rois:
        if r["override"] == "lock":
            rx, ry, rw, rh = r["rect"]
            roi_lock_map[ry:ry + rh, rx:rx + rw] = True
            texture_allowed_map[ry:ry + rh, rx:rx + rw] = False

    drift_guard = np.zeros(shape, dtype=np.float32)
    eff_block = min(block_size, height, width)
    blocks_evaluated = 0
    blocks_flagged = 0
    max_block_shift_px = 0.0
    coherence_values: List[float] = []

    for y0 in range(0, height, eff_block):
        y1 = min(height, y0 + eff_block)
        if y1 - y0 < 3:
            continue
        for x0 in range(0, width, eff_block):
            x1 = min(width, x0 + eff_block)
            if x1 - x0 < 3:
                continue
            dx, dy, improvement = _estimate_patch_shift(ref_lum, cand_lum, y0, x0, y1, x1, search_radius)
            shift_px = float(np.hypot(dx, dy))
            coh = _gradient_coherence(
                gx_r[y0:y1, x0:x1],
                gy_r[y0:y1, x0:x1],
                mag_r[y0:y1, x0:x1],
                gx_c[y0:y1, x0:x1],
                gy_c[y0:y1, x0:x1],
                mag_c[y0:y1, x0:x1],
            )
            blocks_evaluated += 1
            if coh is not None:
                coherence_values.append(coh)
            if shift_px > max_block_shift_px:
                max_block_shift_px = shift_px
            in_texture_zone = bool(np.any(texture_allowed_map[y0:y1, x0:x1]))
            in_unlocked_region = prot_mask is not None and not bool(np.any(prot_mask[y0:y1, x0:x1] == 1.0))
            coh_flag = (
                coh is not None
                and coh < min_edge_coherence
                and not in_texture_zone
                and not (master_rgb is not None and in_unlocked_region)
            )
            if shift_px >= shift_warn_px or coh_flag:
                blocks_flagged += 1
                severity = 1.0 if (shift_px >= shift_fail_px or (coh is not None and coh < min_edge_coherence - 0.15)) else 0.6
                drift_guard[y0:y1, x0:x1] = max(float(drift_guard[y0:y1, x0:x1].max()), severity)

    locked_mismatches = 0
    if master_rgb is not None and prot_mask is not None:
        locked_pixels = prot_mask == 1.0
        if np.any(locked_pixels):
            locked_mismatches = int(np.sum(np.any(master_rgb[locked_pixels] != base_rgb[locked_pixels], axis=-1)))

    roi_reports: List[Dict[str, Any]] = []
    any_fail = locked_mismatches > 0 or max_block_shift_px >= shift_fail_px
    any_warn = (not any_fail) and (
        max_block_shift_px >= shift_warn_px
        or (blocks_flagged > 0 and not (master_rgb is not None and locked_mismatches == 0))
    )

    for roi in norm_rois:
        x, y, w, h = roi["rect"]
        dx, dy, improvement = _estimate_patch_shift(ref_lum, cand_lum, y, x, y + h, x + w, search_radius)
        shift_px = round(float(np.hypot(dx, dy)), 3)
        coh = _gradient_coherence(
            gx_r[y:y + h, x:x + w],
            gy_r[y:y + h, x:x + w],
            mag_r[y:y + h, x:x + w],
            gx_c[y:y + h, x:x + w],
            gy_c[y:y + h, x:x + w],
            mag_c[y:y + h, x:x + w],
        )
        cand_diff = np.abs(cand_rgb[y:y + h, x:x + w].astype(np.int16) - base_rgb[y:y + h, x:x + w].astype(np.int16))
        cand_max_diff = int(cand_diff.max())
        cand_mean_diff = round(float(cand_diff.mean()), 3)

        roi_locked_slice = roi_lock_map[y:y + h, x:x + w]
        expected_locked = bool(np.any(roi_locked_slice))
        master_max_diff: Optional[int] = None
        if master_rgb is not None:
            m_diff = np.abs(master_rgb[y:y + h, x:x + w].astype(np.int16) - base_rgb[y:y + h, x:x + w].astype(np.int16))
            master_max_diff = int(m_diff[roi_locked_slice].max()) if expected_locked else int(m_diff.max())

        roi_is_texture_allowed = (
            (roi["policy"] == "texture_allowed" and roi["override"] != "lock")
            or roi["override"] == "unlock"
        )
        if expected_locked and master_max_diff is not None and master_max_diff > 0:
            roi_status = "LOCK_VIOLATION"
            any_fail = True
        elif shift_px >= shift_fail_px or (
            coh is not None and coh < min_edge_coherence - 0.12 and not roi_is_texture_allowed
        ):
            roi_status = "FAIL_DRIFT"
            any_fail = True
        elif shift_px >= shift_warn_px or (
            coh is not None and coh < min_edge_coherence and not roi_is_texture_allowed
        ):
            roi_status = "WARN_DRIFT"
            any_warn = True
        elif expected_locked and master_max_diff == 0:
            roi_status = "LOCKED_EXACT"
        else:
            roi_status = "PASS"

        roi_reports.append(
            {
                "id": roi["id"],
                "kind": roi["kind"],
                "role": classify_roi_role(roi["kind"]),
                "policy": roi["policy"],
                "override": roi["override"],
                "rect": roi["rect"],
                "expected_locked": expected_locked,
                "status": roi_status,
                "candidate_shift_px": shift_px,
                "candidate_shift_vec": [dx, dy],
                "candidate_shift_improvement": round(improvement, 3),
                "candidate_edge_coherence": round(coh, 4) if coh is not None else None,
                "candidate_max_abs_diff": cand_max_diff,
                "candidate_mean_abs_diff": cand_mean_diff,
                "master_max_abs_diff": master_max_diff,
            }
        )

    verdict = "FAIL" if any_fail else ("WARN" if any_warn else "PASS")
    return {
        "schema_version": 1,
        "dimensions": [width, height],
        "overall_verdict": verdict,
        "blocks_evaluated": blocks_evaluated,
        "blocks_flagged": blocks_flagged,
        "max_block_shift_px": round(max_block_shift_px, 3),
        "min_block_coherence": round(min(coherence_values), 4) if coherence_values else None,
        "locked_pixel_mismatches": locked_mismatches,
        "roi_reports": roi_reports,
        "drift_guard_mask": drift_guard,
        "semantic_proof": False,
        "heuristic_limitations": [
            "Block correlation and Sobel edge coherence detect geometric/gradient mismatch only.",
            "They do not verify OCR readability, facial identity equivalence, or semantic object realism.",
        ],
    }
