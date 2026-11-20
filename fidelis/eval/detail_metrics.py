"""Stable public interface for native-grid detail quality gates."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np

from fidelis.eval.material_metrics import measure_fabric_hardware_faithfulness
from fidelis.eval.roi_normalization import normalize_rois_to_target as _normalize_rois_to_target
from fidelis.eval.texture_metrics import (
    measure_interior_texture_retention,
    measure_oversharpening_restraint,
)

__all__ = [
    "measure_fabric_hardware_faithfulness",
    "measure_interior_texture_retention",
    "measure_oversharpening_restraint",
    "measure_scale_matched_metrics",
]


def _unavailable(reason, **details):
    return {
        "schema_version": 1,
        "status": "unavailable",
        "reason": reason,
        **details,
        "interior_texture_passed": None,
        "oversharpen_restraint_passed": None,
        "fabric_weave_passed": None,
        "hardware_seam_passed": None,
        "all_detail_gates_passed": False,
    }


def _validate_scale_inputs(candidate_bgr, bicubic_bgr, master_bgr):
    if candidate_bgr is None or bicubic_bgr is None:
        return _unavailable("candidate_or_bicubic_missing")

    images = (candidate_bgr, bicubic_bgr)
    if any(image.ndim != 3 or image.shape[2] != 3 for image in images):
        return _unavailable("invalid_image_channels")

    if any(min(image.shape[:2]) <= 0 for image in images):
        return _unavailable("empty_image_dimensions")

    if (
        not np.all(np.isfinite(candidate_bgr))
        or not np.all(np.isfinite(bicubic_bgr))
        or (master_bgr is not None and not np.all(np.isfinite(master_bgr)))
    ):
        return _unavailable("nonfinite_input")

    if candidate_bgr.shape[:2] != bicubic_bgr.shape[:2]:
        return _unavailable(
            "dimension_mismatch_silent_resizing_forbidden",
            candidate_dimensions=[int(candidate_bgr.shape[1]), int(candidate_bgr.shape[0])],
            bicubic_dimensions=[int(bicubic_bgr.shape[1]), int(bicubic_bgr.shape[0])],
        )

    return None


def _rgb_inputs(candidate_bgr, bicubic_bgr, master_bgr, input_color_order):
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

    return cand_rgb, bic_rgb, master_rgb


def measure_scale_matched_metrics(
    candidate_bgr: np.ndarray | None,
    bicubic_bgr: np.ndarray | None,
    source_bgr: np.ndarray | None = None,
    *,
    rois: Sequence[Mapping[str, Any]] | None = None,
    roi_space: str = "auto",
    protected: np.ndarray | None = None,
    master_bgr: np.ndarray | None = None,
    input_color_order: str = "bgr",
) -> dict[str, Any]:
    """Compute F2, F3, and F4 scale-matched native-4x metrics against a bicubic reference."""
    unavailable = _validate_scale_inputs(candidate_bgr, bicubic_bgr, master_bgr)
    if unavailable is not None:
        return unavailable
    cand_rgb, bic_rgb, master_rgb = _rgb_inputs(candidate_bgr, bicubic_bgr, master_bgr, input_color_order)
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
