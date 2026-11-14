"""Tier 2 E2E Tests: Boundary & Corner Cases for F1-F10 (>= 5 tests per feature)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from PIL import Image

from tests.e2e.conftest import (
    REPO_ROOT,
    build_single_case_manifest,
    load_benchmark_protocol_and_slots,
    load_rgb_png,
    make_bicubic_4x,
    make_crema_and_rim_1x,
    make_enhanced_4x,
    make_fabric_and_hardware_1x,
    make_oversharpened_4x,
    make_smoothed_4x,
    save_rgb_png,
)


# ===========================================================================
# F1 Boundaries: Explicit 4x Bicubic Comparator
# ===========================================================================


@pytest.mark.tier2
@pytest.mark.f1
def test_f1_boundary_odd_non_square_dimensions(tmp_path: Path) -> None:
    import fidelis.eval.comparators as comparators

    bicubic_runner = getattr(comparators, "bicubic_runner")
    src = make_crema_and_rim_1x(113, 79, seed=101)
    src_p = save_rgb_png(src, tmp_path / "odd.png")
    dest_p = tmp_path / "odd_4x.png"
    case = {"id": "odd-1", "source_dimensions": [113, 79], "target_dimensions": [452, 316]}
    res = bicubic_runner(case, src_p, dest_p)
    assert res.status == "completed"
    out = load_rgb_png(dest_p)
    assert out.shape == (316, 452, 3)


@pytest.mark.tier2
@pytest.mark.f1
def test_f1_boundary_rejected_unsupported_input_status(tmp_path: Path) -> None:
    import fidelis.eval.comparators as comparators

    bicubic_runner = getattr(comparators, "bicubic_runner")
    src = make_crema_and_rim_1x(64, 64)
    src_p = save_rgb_png(src, tmp_path / "rej.png")
    case = {
        "id": "rej-1",
        "source_dimensions": [64, 64],
        "target_dimensions": [256, 256],
        "expected_behavior": "reject_unsupported_input",
    }
    res = bicubic_runner(case, src_p, tmp_path / "out.png")
    assert res.status == "rejected_unsupported"


@pytest.mark.tier2
@pytest.mark.f1
def test_f1_boundary_missing_source_image_fails_cleanly(tmp_path: Path) -> None:
    import fidelis.eval.comparators as comparators

    bicubic_runner = getattr(comparators, "bicubic_runner")
    case = {"id": "miss-1", "source_dimensions": [64, 64], "target_dimensions": [256, 256]}
    res = bicubic_runner(case, tmp_path / "does_not_exist.png", tmp_path / "out.png")
    assert res.status == "failed"


@pytest.mark.tier2
@pytest.mark.f1
def test_f1_boundary_imported_wrong_dimensions_rejected_by_run_comparators(
    tmp_path: Path, crema_and_rim_1x: np.ndarray
) -> None:
    from fidelis.eval.comparators import make_imported_output_runner, run_comparators

    asset_root = tmp_path / "assets"
    save_rgb_png(crema_and_rim_1x, asset_root / "src.png")
    imp_dir = tmp_path / "imp"
    save_rgb_png(np.zeros((256, 256, 3), dtype=np.uint8), imp_dir / "bad-dim.png")

    manifest = build_single_case_manifest(
        case_id="bad-dim",
        rel_source_path="src.png",
        category="macro",
        source_dimensions=[128, 128],
        target_dimensions=[512, 512],
        rois=[],
        asset_root=asset_root,
    )
    protocol, slots = load_benchmark_protocol_and_slots()
    report = run_comparators(
        manifest,
        asset_root=asset_root,
        output_dir=tmp_path / "out",
        runners={"fidelis": make_imported_output_runner("fidelis", imp_dir)},
        protocol=protocol,
        slots=slots,
        allow_regression_manifest=True,
    )
    rec = report["cases"][0]["outputs"]["fidelis"]
    assert rec["status"] != "completed" or rec.get("error") is not None


@pytest.mark.tier2
@pytest.mark.f1
def test_f1_boundary_1x_identity_target_dimensions(tmp_path: Path, crema_and_rim_1x: np.ndarray) -> None:
    import fidelis.eval.comparators as comparators

    bicubic_runner = getattr(comparators, "bicubic_runner")
    src_p = save_rgb_png(crema_and_rim_1x, tmp_path / "id.png")
    dest_p = tmp_path / "id_1x.png"
    case = {"id": "id-1", "source_dimensions": [128, 128], "target_dimensions": [128, 128]}
    res = bicubic_runner(case, src_p, dest_p)
    assert res.status == "completed"
    assert load_rgb_png(dest_p).shape == (128, 128, 3)


# ===========================================================================
# F2 Boundaries: Scale-Matched Interior Texture Retention
# ===========================================================================


@pytest.mark.tier2
@pytest.mark.f2
def test_f2_boundary_uniform_flat_zero_variance_image() -> None:
    from fidelis.eval.pipeline_metrics import measure_pipeline_metrics

    flat_1x = np.full((64, 64, 3), 128, dtype=np.uint8)
    flat_4x = np.full((256, 256, 3), 128, dtype=np.uint8)
    rois = [{"id": "flat", "kind": "background", "policy": "texture_allowed", "rect": [8, 8, 48, 48]}]
    metrics, _ = measure_pipeline_metrics(
        flat_1x[:, :, ::-1],
        flat_4x[:, :, ::-1],
        bicubic_bgr=flat_4x[:, :, ::-1],
        rois=rois,
    )
    ratio = metrics["interior_texture_retention_ratio"]
    assert ratio is not None and np.isfinite(ratio)


@pytest.mark.tier2
@pytest.mark.f2
def test_f2_boundary_empty_rois_falls_back_cleanly(crema_and_rim_1x: np.ndarray) -> None:
    from fidelis.eval.pipeline_metrics import measure_pipeline_metrics

    bic_4x = make_bicubic_4x(crema_and_rim_1x)
    enh_4x = make_enhanced_4x(crema_and_rim_1x)
    metrics, _ = measure_pipeline_metrics(
        crema_and_rim_1x[:, :, ::-1],
        enh_4x[:, :, ::-1],
        bicubic_bgr=bic_4x[:, :, ::-1],
        rois=[],
    )
    assert np.isfinite(metrics["interior_texture_retention_ratio"])


@pytest.mark.tier2
@pytest.mark.f2
def test_f2_boundary_tiny_4x4_roi(crema_and_rim_1x: np.ndarray) -> None:
    from fidelis.eval.pipeline_metrics import measure_pipeline_metrics

    bic_4x = make_bicubic_4x(crema_and_rim_1x)
    enh_4x = make_enhanced_4x(crema_and_rim_1x)
    rois = [{"id": "tiny", "kind": "background", "policy": "texture_allowed", "rect": [60, 60, 4, 4]}]
    metrics, _ = measure_pipeline_metrics(
        crema_and_rim_1x[:, :, ::-1],
        enh_4x[:, :, ::-1],
        bicubic_bgr=bic_4x[:, :, ::-1],
        rois=rois,
    )
    assert np.isfinite(metrics["interior_texture_retention_ratio"])


@pytest.mark.tier2
@pytest.mark.f2
def test_f2_boundary_odd_non_square_image_and_roi() -> None:
    from fidelis.eval.pipeline_metrics import measure_pipeline_metrics

    src = make_crema_and_rim_1x(97, 63, seed=7)
    bic_4x = make_bicubic_4x(src)
    smooth_4x = make_smoothed_4x(src, sigma=2.2)
    rois = [{"id": "crema", "kind": "background", "policy": "texture_allowed", "rect": [25, 15, 45, 33]}]
    metrics, context = measure_pipeline_metrics(
        src[:, :, ::-1],
        smooth_4x[:, :, ::-1],
        bicubic_bgr=bic_4x[:, :, ::-1],
        rois=rois,
    )
    assert context["comparison_dimensions"] == [388, 252]
    assert metrics["interior_texture_retention_ratio"] < 1.0


@pytest.mark.tier2
@pytest.mark.f2
def test_f2_boundary_saturated_0_255_clipped_image() -> None:
    from fidelis.eval.pipeline_metrics import measure_pipeline_metrics

    src = np.zeros((64, 64, 3), dtype=np.uint8)
    src[::2, ::2] = 255
    bic_4x = make_bicubic_4x(src)
    smooth_4x = make_smoothed_4x(src, sigma=2.0)
    rois = [{"id": "sat", "kind": "background", "policy": "texture_allowed", "rect": [4, 4, 56, 56]}]
    metrics, _ = measure_pipeline_metrics(
        src[:, :, ::-1],
        smooth_4x[:, :, ::-1],
        bicubic_bgr=bic_4x[:, :, ::-1],
        rois=rois,
    )
    assert np.isfinite(metrics["interior_texture_retention_ratio"])
    assert metrics["interior_texture_retention_ratio"] < 1.0


# ===========================================================================
# F3 Boundaries: Oversharpening & Halo Restraint
# ===========================================================================


@pytest.mark.tier2
@pytest.mark.f3
def test_f3_boundary_uniform_flat_image_zero_overshoot() -> None:
    from fidelis.eval.pipeline_metrics import measure_pipeline_metrics

    flat_1x = np.full((64, 64, 3), 100, dtype=np.uint8)
    flat_4x = np.full((256, 256, 3), 100, dtype=np.uint8)
    metrics, _ = measure_pipeline_metrics(
        flat_1x[:, :, ::-1],
        flat_4x[:, :, ::-1],
        bicubic_bgr=flat_4x[:, :, ::-1],
    )
    assert np.isfinite(metrics["edge_overshoot"])
    assert metrics.get("halo_restraint_passed") is True


@pytest.mark.tier2
@pytest.mark.f3
def test_f3_boundary_saturated_0_255_hard_step_edge_clean() -> None:
    from fidelis.eval.pipeline_metrics import measure_pipeline_metrics

    step_1x = np.zeros((64, 64, 3), dtype=np.uint8)
    step_1x[:, 32:] = 255
    bic_4x = make_bicubic_4x(step_1x)
    metrics, _ = measure_pipeline_metrics(
        step_1x[:, :, ::-1],
        bic_4x[:, :, ::-1],
        bicubic_bgr=bic_4x[:, :, ::-1],
    )
    assert metrics.get("halo_restraint_passed") is True


@pytest.mark.tier2
@pytest.mark.f3
def test_f3_boundary_excessive_unsharp_fails_while_bicubic_passes(crema_and_rim_1x: np.ndarray) -> None:
    from fidelis.eval.pipeline_metrics import measure_pipeline_metrics

    bic_4x = make_bicubic_4x(crema_and_rim_1x)
    over_4x = make_oversharpened_4x(crema_and_rim_1x, amount=3.2)
    m_bic, _ = measure_pipeline_metrics(
        crema_and_rim_1x[:, :, ::-1], bic_4x[:, :, ::-1], bicubic_bgr=bic_4x[:, :, ::-1]
    )
    m_over, _ = measure_pipeline_metrics(
        crema_and_rim_1x[:, :, ::-1], over_4x[:, :, ::-1], bicubic_bgr=bic_4x[:, :, ::-1]
    )
    assert m_bic.get("halo_restraint_passed") is True
    assert m_over.get("halo_restraint_passed") is False


@pytest.mark.tier2
@pytest.mark.f3
def test_f3_boundary_single_pixel_impulse_edge() -> None:
    from fidelis.eval.pipeline_metrics import measure_pipeline_metrics

    imp_1x = np.zeros((64, 64, 3), dtype=np.uint8)
    imp_1x[32, 32] = 255
    bic_4x = make_bicubic_4x(imp_1x)
    over_4x = make_oversharpened_4x(imp_1x, amount=3.0)
    metrics, _ = measure_pipeline_metrics(
        imp_1x[:, :, ::-1],
        over_4x[:, :, ::-1],
        bicubic_bgr=bic_4x[:, :, ::-1],
    )
    assert np.isfinite(metrics["edge_overshoot"])


@pytest.mark.tier2
@pytest.mark.f3
def test_f3_boundary_non_square_odd_dimensions() -> None:
    from fidelis.eval.pipeline_metrics import measure_pipeline_metrics

    src = make_crema_and_rim_1x(101, 73, seed=19)
    bic_4x = make_bicubic_4x(src)
    over_4x = make_oversharpened_4x(src, amount=2.8)
    metrics, context = measure_pipeline_metrics(
        src[:, :, ::-1],
        over_4x[:, :, ::-1],
        bicubic_bgr=bic_4x[:, :, ::-1],
    )
    assert context["comparison_dimensions"] == [404, 292]
    assert metrics.get("halo_restraint_passed") is False


# ===========================================================================
# F4 Boundaries: Fabric Weave & Hardware Faithfulness
# ===========================================================================


@pytest.mark.tier2
@pytest.mark.f4
def test_f4_boundary_isotropic_flat_fabric_roi_no_nan() -> None:
    from fidelis.eval.pipeline_metrics import measure_pipeline_metrics

    flat_1x = np.full((64, 64, 3), 90, dtype=np.uint8)
    flat_4x = np.full((256, 256, 3), 90, dtype=np.uint8)
    rois = [{"id": "fab", "kind": "fabric", "policy": "texture_allowed", "rect": [4, 4, 56, 56]}]
    metrics, _ = measure_pipeline_metrics(
        flat_1x[:, :, ::-1],
        flat_4x[:, :, ::-1],
        bicubic_bgr=flat_4x[:, :, ::-1],
        rois=rois,
    )
    assert np.isfinite(metrics["fabric_weave_coherence"])


@pytest.mark.tier2
@pytest.mark.f4
def test_f4_boundary_multiple_overlapping_fabric_and_seam_rois(
    fabric_and_hardware_1x: np.ndarray,
) -> None:
    from fidelis.eval.pipeline_metrics import measure_pipeline_metrics

    bic_4x = make_bicubic_4x(fabric_and_hardware_1x)
    rois = [
        {"id": "fab1", "kind": "fabric", "policy": "texture_allowed", "rect": [4, 4, 70, 116]},
        {"id": "fab2", "kind": "fabric", "policy": "texture_allowed", "rect": [20, 20, 60, 80]},
        {"id": "seam1", "kind": "seam", "policy": "preserve", "rect": [76, 4, 8, 116]},
    ]
    metrics, _ = measure_pipeline_metrics(
        fabric_and_hardware_1x[:, :, ::-1],
        bic_4x[:, :, ::-1],
        bicubic_bgr=bic_4x[:, :, ::-1],
        rois=rois,
    )
    assert metrics.get("fabric_weave_passed") is True
    assert metrics.get("seam_faithfulness_passed") is True


@pytest.mark.tier2
@pytest.mark.f4
def test_f4_boundary_tiny_hardware_roi_2x2_source(fabric_and_hardware_1x: np.ndarray) -> None:
    from fidelis.eval.pipeline_metrics import measure_pipeline_metrics

    bic_4x = make_bicubic_4x(fabric_and_hardware_1x)
    rois = [{"id": "hw_tiny", "kind": "hardware", "policy": "preserve", "rect": [96, 60, 2, 2]}]
    metrics, _ = measure_pipeline_metrics(
        fabric_and_hardware_1x[:, :, ::-1],
        bic_4x[:, :, ::-1],
        bicubic_bgr=bic_4x[:, :, ::-1],
        rois=rois,
    )
    assert metrics.get("hardware_faithfulness_passed") is True


@pytest.mark.tier2
@pytest.mark.f4
def test_f4_boundary_seam_shift_3px_fails_while_0px_passes(
    fabric_and_hardware_1x: np.ndarray,
) -> None:
    from fidelis.eval.pipeline_metrics import measure_pipeline_metrics

    bic_4x = make_bicubic_4x(fabric_and_hardware_1x)
    shifted = bic_4x.copy()
    shifted[16:480, 304:336] = np.roll(bic_4x[16:480, 304:336], shift=3, axis=1)
    rois = [{"id": "seam", "kind": "seam", "policy": "preserve", "rect": [76, 4, 8, 116]}]

    m_clean, _ = measure_pipeline_metrics(
        fabric_and_hardware_1x[:, :, ::-1], bic_4x[:, :, ::-1], bicubic_bgr=bic_4x[:, :, ::-1], rois=rois
    )
    m_shift, _ = measure_pipeline_metrics(
        fabric_and_hardware_1x[:, :, ::-1], shifted[:, :, ::-1], bicubic_bgr=bic_4x[:, :, ::-1], rois=rois
    )
    assert m_clean.get("seam_faithfulness_passed") is True
    assert m_shift.get("seam_faithfulness_passed") is False


@pytest.mark.tier2
@pytest.mark.f4
def test_f4_boundary_non_square_fabric_and_hardware() -> None:
    from fidelis.eval.pipeline_metrics import measure_pipeline_metrics

    src = make_fabric_and_hardware_1x(115, 85, seed=55)
    bic_4x = make_bicubic_4x(src)
    rois = [
        {"id": "fab", "kind": "fabric", "policy": "texture_allowed", "rect": [4, 4, 60, 75]},
        {"id": "hw", "kind": "hardware", "policy": "preserve", "rect": [82, 20, 20, 42]},
    ]
    metrics, _ = measure_pipeline_metrics(
        src[:, :, ::-1],
        bic_4x[:, :, ::-1],
        bicubic_bgr=bic_4x[:, :, ::-1],
        rois=rois,
    )
    assert metrics.get("fabric_weave_passed") is True
    assert metrics.get("hardware_faithfulness_passed") is True


# ===========================================================================
# F5 Boundaries: Texture Guard & Pixel-Lock Preservation
# ===========================================================================


@pytest.mark.tier2
@pytest.mark.f5
def test_f5_boundary_16bit_uint16_compose_regions_exact_lock() -> None:
    from fidelis.postprocess.regions import RegionBlend, compose_regions

    base_u16 = (make_crema_and_rim_1x(64, 64).astype(np.uint16)) * 257
    tex_u16 = np.full_like(base_u16, 65000)
    protected = np.zeros((64, 64), dtype=np.float32)
    protected[:, :32] = 1.0
    res, _ = compose_regions(
        base_u16,
        tex_u16,
        fabric=np.ones((64, 64), dtype=np.float32),
        protected=protected,
        confidence=np.ones((64, 64), dtype=np.float32),
        blend=RegionBlend(fabric=0.5),
        output_dtype=np.uint16,
    )
    assert res.dtype == np.uint16
    assert np.array_equal(res[:, :32], base_u16[:, :32])


@pytest.mark.tier2
@pytest.mark.f5
def test_f5_boundary_8bit_to_16bit_upcast_exact_scaled_lock() -> None:
    from fidelis.postprocess.regions import RegionBlend, compose_regions

    base_u8 = make_crema_and_rim_1x(64, 64)
    tex_u8 = np.full_like(base_u8, 250)
    protected = np.ones((64, 64), dtype=np.float32)
    res, _ = compose_regions(
        base_u8,
        tex_u8,
        fabric=np.ones((64, 64), dtype=np.float32),
        protected=protected,
        confidence=np.ones((64, 64), dtype=np.float32),
        blend=RegionBlend(fabric=0.5),
        output_dtype=np.uint16,
    )
    assert res.dtype == np.uint16
    assert np.array_equal(res, base_u8.astype(np.uint16) * 257)


@pytest.mark.tier2
@pytest.mark.f5
def test_f5_boundary_mismatched_base_texture_shape_raises() -> None:
    from fidelis.postprocess.regions import compose_regions

    base = np.zeros((64, 64, 3), dtype=np.uint8)
    tex = np.zeros((64, 60, 3), dtype=np.uint8)
    with pytest.raises(ValueError):
        compose_regions(base, tex)


@pytest.mark.tier2
@pytest.mark.f5
def test_f5_boundary_screen_internal_drift_shift_warn_vs_fail() -> None:
    from fidelis.postprocess.roi_protection import screen_internal_drift

    base = make_fabric_and_hardware_1x(64, 64)
    cand_warn = np.roll(base, shift=2, axis=1)
    cand_fail = np.roll(base, shift=3, axis=1)

    d_warn = screen_internal_drift(base, cand_warn, shift_warn_px=1.5, shift_fail_px=2.5)
    d_fail = screen_internal_drift(base, cand_fail, shift_warn_px=1.5, shift_fail_px=2.5)
    assert d_warn["overall_verdict"] == "WARN"
    assert d_fail["overall_verdict"] == "FAIL"


@pytest.mark.tier2
@pytest.mark.f5
def test_f5_boundary_out_of_bounds_mask_values_rejected() -> None:
    from fidelis.postprocess.regions import compose_regions

    base = np.zeros((32, 32, 3), dtype=np.uint8)
    bad_mask = np.full((32, 32), 1.5, dtype=np.float32)
    with pytest.raises(ValueError):
        compose_regions(base, base, protected=bad_mask)


# ===========================================================================
# F6 Boundaries: Contour vs. Interior Texture ROI Separation
# ===========================================================================


@pytest.mark.tier2
@pytest.mark.f6
def test_f6_boundary_out_of_bounds_roi_rect_rejected() -> None:
    from fidelis.postprocess.roi_protection import validate_rois

    with pytest.raises(ValueError):
        validate_rois([{"id": "oob", "kind": "hardware", "policy": "preserve", "rect": [50, 50, 20, 20]}], (64, 64))


@pytest.mark.tier2
@pytest.mark.f6
def test_f6_boundary_duplicate_roi_ids_rejected() -> None:
    from fidelis.postprocess.roi_protection import validate_rois

    rois = [
        {"id": "dup", "kind": "hardware", "policy": "preserve", "rect": [0, 0, 10, 10]},
        {"id": "dup", "kind": "fabric", "policy": "texture_allowed", "rect": [10, 10, 10, 10]},
    ]
    with pytest.raises(ValueError):
        validate_rois(rois, (64, 64))


@pytest.mark.tier2
@pytest.mark.f6
def test_f6_boundary_zero_area_roi_rejected() -> None:
    from fidelis.postprocess.roi_protection import validate_rois

    with pytest.raises(ValueError):
        validate_rois([{"id": "z", "kind": "seam", "policy": "preserve", "rect": [5, 5, 0, 10]}], (64, 64))


@pytest.mark.tier2
@pytest.mark.f6
def test_f6_boundary_existing_protected_never_weakened() -> None:
    from fidelis.postprocess.roi_protection import build_roi_protection_masks

    base = np.zeros((64, 64, 3), dtype=np.uint8)
    existing = np.ones((64, 64), dtype=np.float32)
    rois = [{"id": "u", "kind": "hardware", "policy": "preserve", "override": "unlock", "rect": [0, 0, 32, 32]}]
    masks, _ = build_roi_protection_masks(base, rois, existing_protected=existing)
    assert np.all(masks["protected"] == 1.0)


@pytest.mark.tier2
@pytest.mark.f6
def test_f6_boundary_invalid_roi_kind_or_policy_rejected() -> None:
    from fidelis.postprocess.roi_protection import validate_rois

    with pytest.raises(ValueError):
        validate_rois([{"id": "bad", "kind": "unknown_kind", "policy": "preserve", "rect": [0, 0, 10, 10]}], (64, 64))
    with pytest.raises(ValueError):
        validate_rois([{"id": "bad2", "kind": "fabric", "policy": "invalid_policy", "rect": [0, 0, 10, 10]}], (64, 64))


# ===========================================================================
# F7 Boundaries: Pluggable Restoration Model Runner
# ===========================================================================


@pytest.mark.tier2
@pytest.mark.f7
def test_f7_boundary_rgba_4_channel_imported_rejected(tmp_path: Path, crema_and_rim_1x: np.ndarray) -> None:
    from fidelis.engine.runner import ImportedRestorationRunner

    rgba = np.zeros((512, 512, 4), dtype=np.uint8)
    rgba_p = tmp_path / "rgba_4x.png"
    Image.fromarray(rgba, mode="RGBA").save(rgba_p)

    runner = ImportedRestorationRunner(model_id="rgba-test")
    with pytest.raises(ValueError):
        runner.run(crema_and_rim_1x, imported_path=rgba_p, scale=4)


@pytest.mark.tier2
@pytest.mark.f7
def test_f7_boundary_corrupted_non_image_file_raises(tmp_path: Path, crema_and_rim_1x: np.ndarray) -> None:
    from fidelis.engine.runner import ImportedRestorationRunner

    bad_p = tmp_path / "corrupt.png"
    bad_p.write_bytes(b"not a valid png file")
    runner = ImportedRestorationRunner(model_id="corrupt-test")
    with pytest.raises((ValueError, OSError)):
        runner.run(crema_and_rim_1x, imported_path=bad_p, scale=4)


@pytest.mark.tier2
@pytest.mark.f7
def test_f7_boundary_missing_imported_file_raises(tmp_path: Path, crema_and_rim_1x: np.ndarray) -> None:
    from fidelis.engine.runner import ImportedRestorationRunner

    runner = ImportedRestorationRunner(model_id="missing-test")
    with pytest.raises((FileNotFoundError, OSError, ValueError)):
        runner.run(crema_and_rim_1x, imported_path=tmp_path / "missing.png", scale=4)


@pytest.mark.tier2
@pytest.mark.f7
def test_f7_boundary_odd_non_square_4x_grid_preserved(tmp_path: Path) -> None:
    from fidelis.engine.runner import ImportedRestorationRunner

    src = make_crema_and_rim_1x(111, 77, seed=11)
    cand = make_enhanced_4x(src, target_size=(444, 308))
    imp_p = save_rgb_png(cand, tmp_path / "odd_4x.png")
    runner = ImportedRestorationRunner(model_id="odd-test")
    out, _ = runner.run(src, imported_path=imp_p, scale=4)
    assert out.shape == (308, 444, 3)


@pytest.mark.tier2
@pytest.mark.f7
def test_f7_boundary_scale_factor_mismatch_2x_rejected(
    tmp_path: Path, crema_and_rim_1x: np.ndarray
) -> None:
    from fidelis.engine.runner import ImportedRestorationRunner

    two_x = make_bicubic_4x(crema_and_rim_1x, target_size=(256, 256))
    imp_p = save_rgb_png(two_x, tmp_path / "2x.png")
    runner = ImportedRestorationRunner(model_id="scale-mismatch")
    with pytest.raises(ValueError):
        runner.run(crema_and_rim_1x, imported_path=imp_p, scale=4)


# ===========================================================================
# F8 Boundaries: Model-vs-Bicubic Audition Harness
# ===========================================================================


@pytest.mark.tier2
@pytest.mark.f8
def test_f8_boundary_audition_with_empty_rois(tmp_path: Path, crema_and_rim_1x: np.ndarray) -> None:
    from fidelis.studio.audition import run_model_vs_bicubic_audition

    rep = run_model_vs_bicubic_audition(
        source_rgb=crema_and_rim_1x,
        candidate_4x_rgb=make_enhanced_4x(crema_and_rim_1x),
        rois=[],
        output_dir=tmp_path / "empty_rois",
        case_id="empty-rois",
    )
    assert rep["verdict"] in ("PASS", "FAIL")


@pytest.mark.tier2
@pytest.mark.f8
def test_f8_boundary_audition_mismatched_candidate_dimensions_raises(
    tmp_path: Path, crema_and_rim_1x: np.ndarray
) -> None:
    from fidelis.studio.audition import run_model_vs_bicubic_audition

    with pytest.raises(ValueError):
        run_model_vs_bicubic_audition(
            source_rgb=crema_and_rim_1x,
            candidate_4x_rgb=np.zeros((300, 300, 3), dtype=np.uint8),
            rois=[],
            output_dir=tmp_path / "bad_dim",
            case_id="bad-dim",
        )


@pytest.mark.tier2
@pytest.mark.f8
def test_f8_boundary_audition_odd_non_square_image(tmp_path: Path) -> None:
    from fidelis.studio.audition import run_model_vs_bicubic_audition

    src = make_crema_and_rim_1x(105, 75, seed=13)
    cand = make_enhanced_4x(src, target_size=(420, 300))
    rep = run_model_vs_bicubic_audition(
        source_rgb=src,
        candidate_4x_rgb=cand,
        rois=[{"id": "crema", "kind": "background", "policy": "texture_allowed", "rect": [25, 15, 50, 40]}],
        output_dir=tmp_path / "odd_audition",
        case_id="odd-audition",
    )
    assert rep["verdict"] == "PASS"


@pytest.mark.tier2
@pytest.mark.f8
def test_f8_boundary_audition_bicubic_parity_candidate(
    tmp_path: Path, crema_and_rim_1x: np.ndarray
) -> None:
    from fidelis.studio.audition import run_model_vs_bicubic_audition

    bic = make_bicubic_4x(crema_and_rim_1x)
    rep = run_model_vs_bicubic_audition(
        source_rgb=crema_and_rim_1x,
        candidate_4x_rgb=bic,
        rois=[{"id": "crema", "kind": "background", "policy": "texture_allowed", "rect": [36, 36, 56, 56]}],
        output_dir=tmp_path / "bic_parity",
        case_id="bic-parity",
    )
    assert rep["metrics"]["interior_texture_retention_ratio"] == pytest.approx(1.0, abs=1e-4)
    assert rep["metrics"]["halo_restraint_passed"] is True


@pytest.mark.tier2
@pytest.mark.f8
def test_f8_boundary_cli_generate_audition_report_missing_dir_fails(
    tmp_path: Path, run_cli: Any
) -> None:
    proc = run_cli("scripts/generate-audition-report.py", [str(tmp_path / "nonexistent")])
    assert proc.returncode != 0


# ===========================================================================
# F9 Boundaries: Coffee 1000x1000 Regression Case
# ===========================================================================


@pytest.mark.tier2
@pytest.mark.f9
def test_f9_boundary_coffee_wrong_target_size_rejected(
    tmp_path: Path, product_edges_real_path: Path
) -> None:
    from fidelis.studio.audition import run_model_vs_bicubic_audition

    src = load_rgb_png(product_edges_real_path)
    with pytest.raises(ValueError):
        run_model_vs_bicubic_audition(
            source_rgb=src,
            candidate_4x_rgb=np.zeros((1000, 999, 3), dtype=np.uint8),
            rois=[],
            output_dir=tmp_path / "coffee_bad_dim",
            case_id="coffee-bad-dim",
        )


@pytest.mark.tier2
@pytest.mark.f9
def test_f9_boundary_coffee_pure_black_candidate_fails(
    tmp_path: Path, product_edges_real_path: Path
) -> None:
    from fidelis.studio.audition import run_model_vs_bicubic_audition

    src = load_rgb_png(product_edges_real_path)
    coffee_manifest = json.loads(
        (REPO_ROOT / "config" / "benchmark" / "coffee-regression.json").read_text(encoding="utf-8")
    )
    rep = run_model_vs_bicubic_audition(
        source_rgb=src,
        candidate_4x_rgb=np.zeros((1000, 1000, 3), dtype=np.uint8),
        rois=coffee_manifest["cases"][0]["rois"],
        output_dir=tmp_path / "coffee_black",
        case_id="coffee-black",
    )
    assert rep["verdict"] == "FAIL"


@pytest.mark.tier2
@pytest.mark.f9
def test_f9_boundary_coffee_pure_white_candidate_fails(
    tmp_path: Path, product_edges_real_path: Path
) -> None:
    from fidelis.studio.audition import run_model_vs_bicubic_audition

    src = load_rgb_png(product_edges_real_path)
    coffee_manifest = json.loads(
        (REPO_ROOT / "config" / "benchmark" / "coffee-regression.json").read_text(encoding="utf-8")
    )
    rep = run_model_vs_bicubic_audition(
        source_rgb=src,
        candidate_4x_rgb=np.full((1000, 1000, 3), 255, dtype=np.uint8),
        rois=coffee_manifest["cases"][0]["rois"],
        output_dir=tmp_path / "coffee_white",
        case_id="coffee-white",
    )
    assert rep["verdict"] == "FAIL"


@pytest.mark.tier2
@pytest.mark.f9
def test_f9_boundary_coffee_local_crema_only_smoothing_fails(
    tmp_path: Path, product_edges_real_path: Path
) -> None:
    from fidelis.studio.audition import run_model_vs_bicubic_audition

    src = load_rgb_png(product_edges_real_path)
    bic_1000 = make_bicubic_4x(src, target_size=(1000, 1000))
    smooth_1000 = make_smoothed_4x(src, sigma=2.6, target_size=(1000, 1000))
    coffee_manifest = json.loads(
        (REPO_ROOT / "config" / "benchmark" / "coffee-regression.json").read_text(encoding="utf-8")
    )
    rois = coffee_manifest["cases"][0]["rois"]
    crema_roi = next(r for r in rois if r["id"] == "coffee_crema")
    x, y, w, h = [v * 4 for v in crema_roi["rect"]]
    hybrid = bic_1000.copy()
    hybrid[y : y + h, x : x + w] = smooth_1000[y : y + h, x : x + w]

    rep = run_model_vs_bicubic_audition(
        source_rgb=src,
        candidate_4x_rgb=hybrid,
        rois=rois,
        output_dir=tmp_path / "coffee_local_smooth",
        case_id="coffee-local-smooth",
    )
    assert rep["verdict"] == "FAIL"


@pytest.mark.tier2
@pytest.mark.f9
def test_f9_boundary_coffee_rim_halo_only_fails(
    tmp_path: Path, product_edges_real_path: Path
) -> None:
    from fidelis.studio.audition import run_model_vs_bicubic_audition

    src = load_rgb_png(product_edges_real_path)
    enh_1000 = make_enhanced_4x(src, detail_gain=10.0, target_size=(1000, 1000))
    over_1000 = make_oversharpened_4x(src, amount=3.0, target_size=(1000, 1000))
    coffee_manifest = json.loads(
        (REPO_ROOT / "config" / "benchmark" / "coffee-regression.json").read_text(encoding="utf-8")
    )
    rois = coffee_manifest["cases"][0]["rois"]
    preserve_roi = next(r for r in rois if r["policy"] == "preserve")
    x, y, w, h = [v * 4 for v in preserve_roi["rect"]]
    hybrid = enh_1000.copy()
    hybrid[y : y + h, x : x + w] = over_1000[y : y + h, x : x + w]

    rep = run_model_vs_bicubic_audition(
        source_rgb=src,
        candidate_4x_rgb=hybrid,
        rois=rois,
        output_dir=tmp_path / "coffee_rim_halo",
        case_id="coffee-rim-halo",
    )
    assert rep["verdict"] == "FAIL"


# ===========================================================================
# F10 Boundaries: Melato Fabric & Hardware Evaluation Protocol
# ===========================================================================


@pytest.mark.tier2
@pytest.mark.f10
def test_f10_boundary_melato_path_traversal_rejected_by_corpus_manifest(tmp_path: Path) -> None:
    from fidelis.eval.corpus_manifest import local_path

    with pytest.raises(ValueError):
        local_path(tmp_path, "../escape.png")


@pytest.mark.tier2
@pytest.mark.f10
def test_f10_boundary_melato_missing_receipt_fields_fails_acceptance() -> None:
    from fidelis.eval.quality_acceptance import evaluate_held_out_acceptance

    submission = {
        "schema_version": "fidelis.quality_acceptance.v1",
        "calibration_summary": {"recipe_frozen": True, "case_ids": []},
        "automated_metrics": {
            "interior_texture_passed": True,
            "oversharpen_restraint_passed": True,
            "fabric_weave_passed": True,
            "hardware_seam_passed": True,
        },
        "reproducibility_receipt": {"code_sha": "abc"},
        "held_out_ballots": [
            {
                "case_id": f"{cat}-{i:02d}",
                "split": "held_out",
                "category": cat,
                "comparator": "bicubic",
                "outcome": "fidelis_win",
                "critical_defects": [],
            }
            for cat in ("portrait", "model_apparel", "textile", "macro", "packshot_edge")
            for i in range(1, 7)
        ],
    }
    res = evaluate_held_out_acceptance(submission)
    assert res["quantitative_gates_passed"] is False
    assert res["overall_status"] == "failed"
    assert "incomplete_reproducibility_receipt" in res["blocking_reasons"]


@pytest.mark.tier2
@pytest.mark.f10
def test_f10_boundary_melato_below_min_cases_per_category_fails_acceptance() -> None:
    from fidelis.eval.quality_acceptance import evaluate_held_out_acceptance

    submission = {
        "schema_version": "fidelis.quality_acceptance.v1",
        "calibration_summary": {"recipe_frozen": True, "case_ids": []},
        "automated_metrics": {
            "interior_texture_passed": True,
            "oversharpen_restraint_passed": True,
            "fabric_weave_passed": True,
            "hardware_seam_passed": True,
        },
        "reproducibility_receipt": {
            "code_sha": "abc",
            "corpus_lock_sha256": "def",
            "calibration_recipe_sha256": "ghi",
            "runtime_versions": {"python": "3.11"},
            "model_weight_hashes": {"melato": "sha256:000"},
            "seed_policy": "fixed",
            "colour_path": "srgb",
        },
        "held_out_ballots": [
            {
                "case_id": "textile-01",
                "split": "held_out",
                "category": "textile",
                "comparator": "bicubic",
                "outcome": "fidelis_win",
                "critical_defects": [],
            }
        ],
    }
    res = evaluate_held_out_acceptance(submission)
    assert res["quantitative_gates_passed"] is False
    assert res["overall_status"] in ("failed", "blocked_incomplete_evidence")
    assert "incomplete_held_out_category_coverage" in res["blocking_reasons"]


@pytest.mark.tier2
@pytest.mark.f10
def test_f10_boundary_melato_imported_wrong_dimensions_rejected(
    tmp_path: Path, fashion_fabric_real_path: Path
) -> None:
    from fidelis.engine.runner import ImportedRestorationRunner

    src = load_rgb_png(fashion_fabric_real_path)
    wrong_p = save_rgb_png(np.zeros((400, 400, 3), dtype=np.uint8), tmp_path / "melato_2x.png")
    runner = ImportedRestorationRunner(model_id="melato-wrong-dim")
    with pytest.raises(ValueError):
        runner.run(src, imported_path=wrong_p, scale=4)


@pytest.mark.tier2
@pytest.mark.f10
def test_f10_boundary_melato_corrupted_candidate_file_fails(
    tmp_path: Path, fashion_fabric_real_path: Path
) -> None:
    from fidelis.engine.runner import ImportedRestorationRunner

    src = load_rgb_png(fashion_fabric_real_path)
    corrupt_p = tmp_path / "melato_corrupt.png"
    corrupt_p.write_bytes(b"corrupt")
    runner = ImportedRestorationRunner(model_id="melato-corrupt")
    with pytest.raises((ValueError, OSError)):
        runner.run(src, imported_path=corrupt_p, scale=4)
