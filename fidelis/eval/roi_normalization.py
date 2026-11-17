"""Normalize evaluation regions without changing explicit protection intent."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from fidelis.postprocess.roi_protection import VALID_POLICIES, VALID_ROI_KINDS

_CONTOUR_ROI_KINDS = frozenset({"hardware", "seam", "logo", "text"})


def _scales(target_shape, source_shape, roi_space):
    if roi_space not in ("auto", "source", "target"):
        raise ValueError(f"Unsupported roi_space {roi_space!r}")
    if source_shape is None or roi_space == "target":
        return 1.0, 1.0
    th, tw = target_shape
    sh, sw = source_shape
    if sw <= 0 or sh <= 0 or (roi_space == "auto" and target_shape == source_shape):
        return 1.0, 1.0
    return tw / float(sw), th / float(sh)


def _rectangle(entry):
    rect = entry.get("rect")
    if isinstance(rect, (list, tuple)) and len(rect) == 4:
        return [float(v) for v in rect]
    bbox = entry.get("bbox")
    if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
        x0, y0, x1, y1 = [float(v) for v in bbox]
        return x0, y0, x1 - x0, y1 - y0
    return None


def _clip(rect, target_shape, scales):
    rx, ry, rw, rh = rect
    scale_x, scale_y = scales
    th, tw = target_shape
    tx, ty = round(rx * scale_x), round(ry * scale_y)
    width, height = round(rw * scale_x), round(rh * scale_y)
    if width <= 0 or height <= 0:
        return None
    x0, y0 = max(0, tx), max(0, ty)
    x1, y1 = min(tw, tx + width), min(th, ty + height)
    return [x0, y0, x1 - x0, y1 - y0] if x1 > x0 and y1 > y0 else None


def _metadata(entry, idx, seen_ids):
    kind = str(entry.get("kind", "fabric"))
    drift_kind = "background" if kind not in VALID_ROI_KINDS and kind == "crema" else kind
    raw_policy = entry.get("policy")
    if raw_policy in VALID_POLICIES:
        policy = str(raw_policy)
    else:
        policy = "preserve" if kind in _CONTOUR_ROI_KINDS or kind == "identity" else "texture_allowed"
    override = entry.get("override")
    if override not in (None, "lock", "unlock"):
        override = None
    rid = str(entry.get("id") or f"roi_{idx}").strip() or f"roi_{idx}"
    while rid in seen_ids:
        rid = f"{rid}_{idx}"
    seen_ids.add(rid)
    return {
        "id": rid, "kind": kind, "drift_kind": drift_kind, "policy": policy,
        "override": override, "label": str(entry.get("label", rid)),
    }


def normalize_rois_to_target(
    rois: Sequence[Mapping[str, Any]] | None,
    target_shape: tuple[int, int],
    source_shape: tuple[int, int] | None = None,
    roi_space: str = "auto",
) -> list[dict[str, Any]]:
    """Normalize rect or bbox coordinates into the target pixel grid."""
    if not rois:
        return []
    scales = _scales(target_shape, source_shape, roi_space)
    normalized = []
    seen_ids: set[str] = set()
    for idx, entry in enumerate(rois):
        if not isinstance(entry, Mapping):
            continue
        rect = _rectangle(entry)
        clipped = _clip(rect, target_shape, scales) if rect is not None else None
        if clipped is None:
            continue
        normalized.append({**_metadata(entry, idx, seen_ids), "rect": clipped})
    return normalized
