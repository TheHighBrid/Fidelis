"""Tier 1 E2E Tests: Per-Feature Coverage for F1-F10 (>= 5 tests per feature)."""

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
    sha256_file,
)


# ===========================================================================
# F1: Explicit 4x Bicubic Comparator
# ===========================================================================


@pytest.mark.tier1
@pytest.mark.f1
def test_f1_bicubic_in_canonical_comparators() -> None:
    from fidelis.eval.comparators import CANONICAL_COMPARATORS

    assert "bicubic" in CANONICAL_COMPARATORS
    assert "interpolation" in CANONICAL_COMPARATORS


@pytest.mark.tier1
@pytest.mark.f1
def test_f1_bicubic_runner_matches_pil_bicubic(tmp_path: Path, crema_and_rim_1x: np.ndarray) -> None:
    import fidelis.eval.comparators as comparators

    bicubic_runner = getattr(comparators, "bicubic_runner", None)
    assert callable(bicubic_runner), "fidelis.eval.comparators.bicubic_runner must exist"

    src_path = save_rgb_png(crema_and_rim_1x, tmp_path / "src.png")
    dest_path = tmp_path / "out_bicubic.png"
    case = {
        "id": "case-f1-01",
        "source_dimensions": [128, 128],
        "target_dimensions": [512, 512],
    }

    result = bicubic_runner(case, src_path, dest_path)
    assert result.status == "completed"
    assert result.output_path == dest_path
    assert dest_path.is_file()
    assert result.settings.get("method") == "bicubic"

    actual = load_rgb_png(dest_path)
    expected = make_bicubic_4x(crema_and_rim_1x, target_size=(512, 512))
    assert actual.shape == (512, 512, 3)
    assert np.array_equal(actual, expected)


@pytest.mark.tier1
@pytest.mark.f1
def test_f1_run_comparators_includes_bicubic_and_lanczos(
    tmp_path: Path, crema_and_rim_1x: np.ndarray
) -> None:
    import fidelis.eval.comparators as comparators

    assert "bicubic" in comparators.CANONICAL_COMPARATORS

    asset_root = tmp_path / "assets"
    src_rel = "crops/crema.png"
    save_rgb_png(crema_and_rim_1x, asset_root / src_rel)
    manifest = build_single_case_manifest(
        case_id="crema-01",
        rel_source_path=src_rel,
        category="macro",
        source_dimensions=[128, 128],
        target_dimensions=[512, 512],
        rois=[],
        asset_root=asset_root,
    )
    protocol, slots = load_benchmark_protocol_and_slots()
    out_dir = tmp_path / "out"
    report = comparators.run_comparators(
        manifest,
        asset_root=asset_root,
        output_dir=out_dir,
        protocol=protocol,
        slots=slots,
        allow_regression_manifest=True,
    )
    assert "bicubic" in report["comparators"]
    assert "interpolation" in report["comparators"]
    case_comp = report["cases"][0]["outputs"]
    assert case_comp["bicubic"]["status"] == "completed"
    assert case_comp["interpolation"]["status"] == "completed"
    bic_img = load_rgb_png(Path(case_comp["bicubic"]["output_path"]))
    lan_img = load_rgb_png(Path(case_comp["interpolation"]["output_path"]))
    assert bic_img.shape == (512, 512, 3)
    assert not np.array_equal(bic_img, lan_img)


@pytest.mark.tier1
@pytest.mark.f1
def test_f1_cli_run_comparators_bicubic_and_blind_manifest(
    tmp_path: Path, crema_and_rim_1x: np.ndarray, run_cli: Any
) -> None:
    asset_root = tmp_path / "assets"
    save_rgb_png(crema_and_rim_1x, asset_root / "crema.png")
    imported_dir = tmp_path / "imported_fidelis"
    save_rgb_png(make_enhanced_4x(crema_and_rim_1x), imported_dir / "crema-cli.png")

    manifest = build_single_case_manifest(
        case_id="crema-cli",
        rel_source_path="crema.png",
        category="macro",
        source_dimensions=[128, 128],
        target_dimensions=[512, 512],
        rois=[],
        asset_root=asset_root,
    )
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    out_dir = tmp_path / "cli_out"
    proc = run_cli(
        "scripts/run-comparators.py",
        [
            "run",
            str(manifest_path),
            "--root",
            str(asset_root),
            "--output-dir",
            str(out_dir),
            "--imported-dir",
            f"fidelis={imported_dir}",
            "--allow-regression-manifest",
            "--blind-pair",
            "bicubic",
            "fidelis",
            "--blind-split",
            "regression",
        ],
    )
    assert proc.returncode == 0, f"CLI failed: {proc.stderr}"
    report = json.loads((out_dir / "comparison-report.json").read_text(encoding="utf-8"))
    assert "bicubic" in report["comparators"]
    assert report["cases"][0]["outputs"]["bicubic"]["status"] == "completed"
    assert (out_dir / "blind-ballot.json").is_file()
    assert (out_dir / "blind-answer-key.json").is_file()


@pytest.mark.tier1
@pytest.mark.f1
def test_f1_protocol_v1_lists_bicubic_comparator() -> None:
    protocol = json.loads((REPO_ROOT / "config" / "benchmark" / "protocol-v1.json").read_text(encoding="utf-8"))
    assert "bicubic" in protocol["comparators"]


# ===========================================================================
# F2: Scale-Matched Native 4x Interior Texture Retention Metric
# ===========================================================================


@pytest.mark.tier1
@pytest.mark.f2
def test_f2_native_4x_comparison_without_downsampling(crema_and_rim_1x: np.ndarray) -> None:
    from fidelis.eval.pipeline_metrics import measure_pipeline_metrics

    bic_4x = make_bicubic_4x(crema_and_rim_1x)
    enh_4x = make_enhanced_4x(crema_and_rim_1x)
    rois = [{"id": "crema", "kind": "background", "policy": "texture_allowed", "rect": [36, 36, 56, 56]}]

    metrics, context = measure_pipeline_metrics(
        crema_and_rim_1x[:, :, ::-1],
        enh_4x[:, :, ::-1],
        bicubic_bgr=bic_4x[:, :, ::-1],
        rois=rois,
    )
    assert context["comparison_dimensions"] == [512, 512]
    assert context["comparison"] != "output_area_downsampled_to_source"
    assert "interior_texture_retention_ratio" in metrics
    assert metrics["interior_texture_retention_ratio"] is not None


@pytest.mark.tier1
@pytest.mark.f2
def test_f2_smoothed_crema_fails_texture_retention(crema_and_rim_1x: np.ndarray) -> None:
    from fidelis.eval.pipeline_metrics import measure_pipeline_metrics

    bic_4x = make_bicubic_4x(crema_and_rim_1x)
    smoothed_4x = make_smoothed_4x(crema_and_rim_1x, sigma=2.5)
    rois = [{"id": "crema", "kind": "background", "policy": "texture_allowed", "rect": [36, 36, 56, 56]}]

    metrics, _ = measure_pipeline_metrics(
        crema_and_rim_1x[:, :, ::-1],
        smoothed_4x[:, :, ::-1],
        bicubic_bgr=bic_4x[:, :, ::-1],
        rois=rois,
    )
    assert metrics["interior_texture_retention_ratio"] < 1.0
    assert metrics.get("texture_retention_passed") is False


@pytest.mark.tier1
@pytest.mark.f2
def test_f2_bicubic_baseline_passes_at_parity(crema_and_rim_1x: np.ndarray) -> None:
    from fidelis.eval.pipeline_metrics import measure_pipeline_metrics

    bic_4x = make_bicubic_4x(crema_and_rim_1x)
    rois = [{"id": "crema", "kind": "background", "policy": "texture_allowed", "rect": [36, 36, 56, 56]}]

    metrics, _ = measure_pipeline_metrics(
        crema_and_rim_1x[:, :, ::-1],
        bic_4x[:, :, ::-1],
        bicubic_bgr=bic_4x[:, :, ::-1],
        rois=rois,
    )
    assert metrics["interior_texture_retention_ratio"] == pytest.approx(1.0, abs=1e-4)
    assert metrics.get("texture_retention_passed") is True


@pytest.mark.tier1
@pytest.mark.f2
def test_f2_enhanced_4x_passes_texture_retention_above_bicubic(crema_and_rim_1x: np.ndarray) -> None:
    from fidelis.eval.pipeline_metrics import measure_pipeline_metrics

    bic_4x = make_bicubic_4x(crema_and_rim_1x)
    enh_4x = make_enhanced_4x(crema_and_rim_1x, detail_gain=12.0)
    rois = [{"id": "crema", "kind": "background", "policy": "texture_allowed", "rect": [36, 36, 56, 56]}]

    metrics, _ = measure_pipeline_metrics(
        crema_and_rim_1x[:, :, ::-1],
        enh_4x[:, :, ::-1],
        bicubic_bgr=bic_4x[:, :, ::-1],
        rois=rois,
    )
    assert metrics["interior_texture_retention_ratio"] >= 1.0
    assert metrics.get("texture_retention_passed") is True


@pytest.mark.tier1
@pytest.mark.f2
def test_f2_roi_scoping_detects_smoothed_crema_despite_crisp_rim(crema_and_rim_1x: np.ndarray) -> None:
    from fidelis.eval.pipeline_metrics import measure_pipeline_metrics

    bic_4x = make_bicubic_4x(crema_and_rim_1x)
    smoothed_4x = make_smoothed_4x(crema_and_rim_1x, sigma=2.5)
    # Keep rim area crisp (copied from bicubic), only interior crema is smoothed
    hybrid = bic_4x.copy()
    hybrid[144:368, 144:368] = smoothed_4x[144:368, 144:368]
    rois = [
        {"id": "crema", "kind": "background", "policy": "texture_allowed", "rect": [36, 36, 56, 56]},
        {"id": "rim", "kind": "hardware", "policy": "preserve", "rect": [10, 10, 20, 20]},
    ]
    metrics, _ = measure_pipeline_metrics(
        crema_and_rim_1x[:, :, ::-1],
        hybrid[:, :, ::-1],
        bicubic_bgr=bic_4x[:, :, ::-1],
        rois=rois,
    )
    assert metrics["interior_texture_retention_ratio"] < 1.0
    assert metrics.get("texture_retention_passed") is False


# ===========================================================================
# F3: Oversharpening & Halo Restraint Metric
# ===========================================================================


@pytest.mark.tier1
@pytest.mark.f3
def test_f3_oversharpened_output_fails_halo_restraint(crema_and_rim_1x: np.ndarray) -> None:
    from fidelis.eval.pipeline_metrics import measure_pipeline_metrics

    bic_4x = make_bicubic_4x(crema_and_rim_1x)
    over_4x = make_oversharpened_4x(crema_and_rim_1x, amount=2.8)
    metrics, _ = measure_pipeline_metrics(
        crema_and_rim_1x[:, :, ::-1],
        over_4x[:, :, ::-1],
        bicubic_bgr=bic_4x[:, :, ::-1],
    )
    assert "edge_overshoot" in metrics
    assert "nyquist_midband_ratio" in metrics
    assert metrics.get("halo_restraint_passed") is False


@pytest.mark.tier1
@pytest.mark.f3
def test_f3_bicubic_reference_passes_halo_restraint(crema_and_rim_1x: np.ndarray) -> None:
    from fidelis.eval.pipeline_metrics import measure_pipeline_metrics

    bic_4x = make_bicubic_4x(crema_and_rim_1x)
    metrics, _ = measure_pipeline_metrics(
        crema_and_rim_1x[:, :, ::-1],
        bic_4x[:, :, ::-1],
        bicubic_bgr=bic_4x[:, :, ::-1],
    )
    assert metrics.get("halo_restraint_passed") is True


@pytest.mark.tier1
@pytest.mark.f3
def test_f3_genuine_enhancement_passes_halo_restraint(crema_and_rim_1x: np.ndarray) -> None:
    from fidelis.eval.pipeline_metrics import measure_pipeline_metrics

    bic_4x = make_bicubic_4x(crema_and_rim_1x)
    enh_4x = make_enhanced_4x(crema_and_rim_1x, detail_gain=10.0)
    metrics, _ = measure_pipeline_metrics(
        crema_and_rim_1x[:, :, ::-1],
        enh_4x[:, :, ::-1],
        bicubic_bgr=bic_4x[:, :, ::-1],
    )
    assert metrics.get("halo_restraint_passed") is True


@pytest.mark.tier1
@pytest.mark.f3
def test_f3_nyquist_ringing_detected_on_hard_contours(crema_and_rim_1x: np.ndarray) -> None:
    from fidelis.eval.pipeline_metrics import measure_pipeline_metrics

    bic_4x = make_bicubic_4x(crema_and_rim_1x)
    ringing = bic_4x.astype(np.float32)
    h, w = ringing.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w]
    ringing += (((xx + yy) % 2) * 2.0 - 1.0)[..., None] * 18.0
    ringing_u8 = np.clip(np.round(ringing), 0, 255).astype(np.uint8)

    metrics, _ = measure_pipeline_metrics(
        crema_and_rim_1x[:, :, ::-1],
        ringing_u8[:, :, ::-1],
        bicubic_bgr=bic_4x[:, :, ::-1],
    )
    assert metrics["nyquist_midband_ratio"] > 0.0
    assert metrics.get("halo_restraint_passed") is False


@pytest.mark.tier1
@pytest.mark.f3
def test_f3_sharpening_only_fails_overall_even_with_edge_energy_gain(
    crema_and_rim_1x: np.ndarray,
) -> None:
    from fidelis.eval.benchmark_suite import BenchmarkSuite

    over_4x = make_oversharpened_4x(crema_and_rim_1x, amount=2.8)
    suite = BenchmarkSuite()
    report = suite.evaluate_pair(crema_and_rim_1x, over_4x)
    assert report.quality_verdict == "FAIL"


# ===========================================================================
# F4: Fabric Weave & Hardware Faithfulness Metrics
# ===========================================================================


@pytest.mark.tier1
@pytest.mark.f4
def test_f4_fabric_weave_orientation_coherence_passes_faithful(
    fabric_and_hardware_1x: np.ndarray,
) -> None:
    from fidelis.eval.pipeline_metrics import measure_pipeline_metrics

    bic_4x = make_bicubic_4x(fabric_and_hardware_1x)
    enh_4x = make_enhanced_4x(fabric_and_hardware_1x, detail_gain=8.0)
    rois = [
        {"id": "fabric_1", "kind": "fabric", "policy": "texture_allowed", "rect": [4, 4, 70, 116]},
        {"id": "seam_1", "kind": "seam", "policy": "preserve", "rect": [76, 4, 8, 116]},
        {"id": "hw_1", "kind": "hardware", "policy": "preserve", "rect": [90, 30, 28, 64]},
    ]
    metrics, _ = measure_pipeline_metrics(
        fabric_and_hardware_1x[:, :, ::-1],
        enh_4x[:, :, ::-1],
        bicubic_bgr=bic_4x[:, :, ::-1],
        rois=rois,
    )
    assert "fabric_weave_coherence" in metrics
    assert metrics.get("fabric_weave_passed") is True


@pytest.mark.tier1
@pytest.mark.f4
def test_f4_warped_weave_fails_orientation_coherence(fabric_and_hardware_1x: np.ndarray) -> None:
    from fidelis.eval.pipeline_metrics import measure_pipeline_metrics

    bic_4x = make_bicubic_4x(fabric_and_hardware_1x)
    warped = bic_4x.copy()
    # Replace fabric ROI (4*4..74*4) with orthogonal stripes instead of diagonal twill
    yy, xx = np.mgrid[16:480, 16:296].astype(np.float32)
    warped[16:480, 16:296] = np.clip(90.0 + 35.0 * np.sin(2.0 * np.pi * yy / 6.0), 0, 255).astype(np.uint8)[
        ..., None
    ]
    rois = [{"id": "fabric_1", "kind": "fabric", "policy": "texture_allowed", "rect": [4, 4, 70, 116]}]
    metrics, _ = measure_pipeline_metrics(
        fabric_and_hardware_1x[:, :, ::-1],
        warped[:, :, ::-1],
        bicubic_bgr=bic_4x[:, :, ::-1],
        rois=rois,
    )
    assert metrics.get("fabric_weave_passed") is False


@pytest.mark.tier1
@pytest.mark.f4
def test_f4_hardware_roi_overshoot_fails_zero_overshoot_check(
    fabric_and_hardware_1x: np.ndarray,
) -> None:
    from fidelis.eval.pipeline_metrics import measure_pipeline_metrics

    bic_4x = make_bicubic_4x(fabric_and_hardware_1x)
    over_4x = make_oversharpened_4x(fabric_and_hardware_1x, amount=3.0)
    cand = bic_4x.copy()
    cand[120:376, 360:472] = over_4x[120:376, 360:472]
    rois = [{"id": "hw_1", "kind": "hardware", "policy": "preserve", "rect": [90, 30, 28, 64]}]
    metrics, _ = measure_pipeline_metrics(
        fabric_and_hardware_1x[:, :, ::-1],
        cand[:, :, ::-1],
        bicubic_bgr=bic_4x[:, :, ::-1],
        rois=rois,
    )
    assert metrics.get("hardware_faithfulness_passed") is False


@pytest.mark.tier1
@pytest.mark.f4
def test_f4_seam_roi_spatial_shift_fails_zero_drift_check(
    fabric_and_hardware_1x: np.ndarray,
) -> None:
    from fidelis.eval.pipeline_metrics import measure_pipeline_metrics

    bic_4x = make_bicubic_4x(fabric_and_hardware_1x)
    shifted = bic_4x.copy()
    shifted[16:480, 308:340] = np.roll(bic_4x[16:480, 308:340], shift=4, axis=1)
    rois = [{"id": "seam_1", "kind": "seam", "policy": "preserve", "rect": [77, 4, 8, 116]}]
    metrics, _ = measure_pipeline_metrics(
        fabric_and_hardware_1x[:, :, ::-1],
        shifted[:, :, ::-1],
        bicubic_bgr=bic_4x[:, :, ::-1],
        rois=rois,
    )
    assert metrics.get("seam_faithfulness_passed") is False


@pytest.mark.tier1
@pytest.mark.f4
def test_f4_faithful_fabric_and_hardware_passes_all_gates(
    fabric_and_hardware_1x: np.ndarray,
) -> None:
    from fidelis.eval.pipeline_metrics import measure_pipeline_metrics

    bic_4x = make_bicubic_4x(fabric_and_hardware_1x)
    enh_4x = make_enhanced_4x(fabric_and_hardware_1x, detail_gain=8.0)
    # Lock hardware and seam to exact bicubic
    enh_4x[16:480, 304:336] = bic_4x[16:480, 304:336]
    enh_4x[120:376, 360:472] = bic_4x[120:376, 360:472]
    rois = [
        {"id": "fabric_1", "kind": "fabric", "policy": "texture_allowed", "rect": [4, 4, 70, 116]},
        {"id": "seam_1", "kind": "seam", "policy": "preserve", "rect": [76, 4, 8, 116]},
        {"id": "hw_1", "kind": "hardware", "policy": "preserve", "rect": [90, 30, 28, 64]},
    ]
    metrics, _ = measure_pipeline_metrics(
        fabric_and_hardware_1x[:, :, ::-1],
        enh_4x[:, :, ::-1],
        bicubic_bgr=bic_4x[:, :, ::-1],
        rois=rois,
    )
    assert metrics.get("fabric_weave_passed") is True
    assert metrics.get("hardware_faithfulness_passed") is True
    assert metrics.get("seam_faithfulness_passed") is True


# ===========================================================================
# F5: Texture Guard & Pixel-Lock Preservation
# ===========================================================================


@pytest.mark.tier1
@pytest.mark.f5
def test_f5_compose_regions_exact_base_restoration_when_protected(
    crema_and_rim_1x: np.ndarray,
) -> None:
    from fidelis.postprocess.regions import RegionBlend, compose_regions

    base = make_bicubic_4x(crema_and_rim_1x)
    texture = np.full_like(base, 250)
    protected = np.zeros(base.shape[:2], dtype=np.float32)
    protected[:256, :256] = 1.0
    fabric = np.ones(base.shape[:2], dtype=np.float32)
    confidence = np.ones(base.shape[:2], dtype=np.float32)

    result, alpha = compose_regions(
        base,
        texture,
        fabric=fabric,
        protected=protected,
        confidence=confidence,
        blend=RegionBlend(fabric=0.5),
    )
    assert np.all(alpha[:256, :256] == 0.0)
    assert np.array_equal(result[:256, :256], base[:256, :256])
    assert not np.array_equal(result[256:, 256:], base[256:, 256:])


@pytest.mark.tier1
@pytest.mark.f5
def test_f5_compose_regions_alpha_zero_when_confidence_missing(
    crema_and_rim_1x: np.ndarray,
) -> None:
    from fidelis.postprocess.regions import RegionBlend, compose_regions

    base = make_bicubic_4x(crema_and_rim_1x)
    texture = make_enhanced_4x(crema_and_rim_1x)
    fabric = np.ones(base.shape[:2], dtype=np.float32)

    result, alpha = compose_regions(
        base,
        texture,
        fabric=fabric,
        confidence=None,
        blend=RegionBlend(fabric=0.5),
    )
    assert np.all(alpha == 0.0)
    assert np.array_equal(result, base)


@pytest.mark.tier1
@pytest.mark.f5
def test_f5_build_masks_compose_and_screen_drift_pass(
    fabric_and_hardware_1x: np.ndarray,
) -> None:
    from fidelis.postprocess.regions import RegionBlend, compose_regions
    from fidelis.postprocess.roi_protection import build_roi_protection_masks, screen_internal_drift

    base = make_bicubic_4x(fabric_and_hardware_1x)
    texture = make_enhanced_4x(fabric_and_hardware_1x)
    rois = [
        {"id": "hw", "kind": "hardware", "policy": "preserve", "rect": [360, 120, 112, 256]},
        {"id": "fab", "kind": "fabric", "policy": "texture_allowed", "rect": [16, 16, 280, 464]},
    ]
    masks, _ = build_roi_protection_masks(base, rois)
    fabric = np.ones(base.shape[:2], dtype=np.float32)
    confidence = np.ones(base.shape[:2], dtype=np.float32)
    master, _ = compose_regions(
        base,
        texture,
        fabric=fabric,
        protected=masks["protected"],
        confidence=confidence,
        blend=RegionBlend(fabric=0.35),
    )
    drift = screen_internal_drift(base, texture, rois=rois, protected=masks["protected"], master=master)
    assert drift["locked_pixel_mismatches"] == 0
    assert drift["overall_verdict"] == "PASS"


@pytest.mark.tier1
@pytest.mark.f5
def test_f5_screen_internal_drift_flags_lock_violation_and_shift(
    fabric_and_hardware_1x: np.ndarray,
) -> None:
    from fidelis.postprocess.roi_protection import build_roi_protection_masks, screen_internal_drift

    base = make_bicubic_4x(fabric_and_hardware_1x)
    rois = [{"id": "hw", "kind": "hardware", "policy": "preserve", "rect": [360, 120, 112, 256]}]
    masks, _ = build_roi_protection_masks(base, rois)

    # Mutate master inside protected ROI + shift candidate
    master = base.copy()
    master[150, 400] = np.clip(master[150, 400].astype(np.int16) + 20, 0, 255).astype(np.uint8)
    candidate = np.roll(base, shift=3, axis=1)

    drift = screen_internal_drift(base, candidate, rois=rois, protected=masks["protected"], master=master)
    assert drift["locked_pixel_mismatches"] >= 1
    assert drift["overall_verdict"] == "FAIL"
    assert any(r["status"] == "LOCK_VIOLATION" for r in drift["roi_reports"])


@pytest.mark.tier1
@pytest.mark.f5
def test_f5_export_verified_master_round_trip(
    tmp_path: Path, fabric_and_hardware_1x: np.ndarray
) -> None:
    from fidelis.postprocess.managed_export import (
        compose_managed_passes,
        export_verified_master,
        load_managed_pass,
    )
    from fidelis.postprocess.regions import RegionBlend
    from fidelis.postprocess.roi_protection import build_roi_protection_masks

    base_arr = make_bicubic_4x(fabric_and_hardware_1x)
    tex_arr = make_enhanced_4x(fabric_and_hardware_1x)
    base_path = save_rgb_png(base_arr, tmp_path / "base.png")
    tex_path = save_rgb_png(tex_arr, tmp_path / "tex.png")

    base_img = load_managed_pass(base_path)
    tex_img = load_managed_pass(tex_path)
    rois = [{"id": "hw", "kind": "hardware", "policy": "preserve", "rect": [360, 120, 112, 256]}]
    masks, _ = build_roi_protection_masks(base_arr, rois)

    composed, _, meta = compose_managed_passes(
        base_img,
        tex_img,
        fabric=np.ones(base_arr.shape[:2], dtype=np.float32),
        protected=masks["protected"],
        confidence=np.ones(base_arr.shape[:2], dtype=np.float32),
        blend=RegionBlend(fabric=0.25),
    )
    out_path = tmp_path / "master.png"
    master_p, recipe_p, _ = export_verified_master(
        out_path,
        composed,
        meta,
        input_paths={"base": base_path, "texture": tex_path},
        profile="luxury_apparel",
    )
    assert master_p.is_file()
    assert recipe_p.is_file()
    reloaded = load_rgb_png(master_p)
    assert np.array_equal(reloaded[120:376, 360:472], base_arr[120:376, 360:472])


# ===========================================================================
# F6: Contour vs. Interior Texture ROI Separation
# ===========================================================================


@pytest.mark.tier1
@pytest.mark.f6
def test_f6_preserve_vs_texture_allowed_separation(fabric_and_hardware_1x: np.ndarray) -> None:
    from fidelis.postprocess.roi_protection import build_roi_protection_masks

    base = make_bicubic_4x(fabric_and_hardware_1x)
    rois = [
        {"id": "fab", "kind": "fabric", "policy": "texture_allowed", "rect": [16, 16, 200, 400]},
        {"id": "hw", "kind": "hardware", "policy": "preserve", "rect": [360, 120, 100, 200]},
        {"id": "seam", "kind": "seam", "policy": "preserve", "rect": [304, 16, 32, 400]},
    ]
    masks, receipt = build_roi_protection_masks(base, rois)
    assert np.all(masks["protected"][16:416, 16:216] == 0.0)
    assert np.all(masks["protected"][120:320, 360:460] == 1.0)
    assert np.all(masks["protected"][16:416, 304:336] == 1.0)
    assert set(receipt["locked_roi_ids"]) == {"hw", "seam"}


@pytest.mark.tier1
@pytest.mark.f6
def test_f6_lock_and_unlock_overrides_precedence(fabric_and_hardware_1x: np.ndarray) -> None:
    from fidelis.postprocess.roi_protection import build_roi_protection_masks

    base = make_bicubic_4x(fabric_and_hardware_1x)
    rois = [
        {"id": "fab_locked", "kind": "fabric", "policy": "texture_allowed", "override": "lock", "rect": [16, 16, 64, 64]},
        {"id": "hw_unlocked", "kind": "hardware", "policy": "preserve", "override": "unlock", "rect": [360, 120, 64, 64]},
    ]
    masks, receipt = build_roi_protection_masks(base, rois, use_sobel_heuristic=True)
    assert np.all(masks["protected"][16:80, 16:80] == 1.0)
    assert np.all(masks["protected"][120:184, 360:424] == 0.0)
    assert np.all(masks["edge_guard"][120:184, 360:424] == 0.0)
    assert receipt["forced_lock_override_ids"] == ["fab_locked"]
    assert receipt["unlocked_override_ids"] == ["hw_unlocked"]


@pytest.mark.tier1
@pytest.mark.f6
def test_f6_sobel_edge_guard_bounded_below_one(crema_and_rim_1x: np.ndarray) -> None:
    from fidelis.postprocess.roi_protection import build_roi_protection_masks

    base = make_bicubic_4x(crema_and_rim_1x)
    masks, receipt = build_roi_protection_masks(
        base, [], use_sobel_heuristic=True, sobel_strength=0.35, max_sobel_guard=0.65
    )
    assert receipt["sobel_heuristic_enabled"] is True
    assert receipt["sobel_is_semantic_proof"] is False
    assert float(masks["edge_guard"].max()) <= 0.65 + 1e-6
    assert float(masks["edge_guard"].max()) > 0.0


@pytest.mark.tier1
@pytest.mark.f6
def test_f6_no_texture_bleed_into_preserve_rois(fabric_and_hardware_1x: np.ndarray) -> None:
    from fidelis.postprocess.regions import RegionBlend, compose_regions
    from fidelis.postprocess.roi_protection import build_roi_protection_masks

    base = make_bicubic_4x(fabric_and_hardware_1x)
    texture = np.clip(base.astype(np.int16) + 60, 0, 255).astype(np.uint8)
    rois = [
        {"id": "fab", "kind": "fabric", "policy": "texture_allowed", "rect": [16, 16, 200, 400]},
        {"id": "hw", "kind": "hardware", "policy": "preserve", "rect": [360, 120, 100, 200]},
    ]
    masks, _ = build_roi_protection_masks(base, rois)
    master, _ = compose_regions(
        base,
        texture,
        fabric=np.ones(base.shape[:2], dtype=np.float32),
        protected=masks["protected"],
        confidence=np.ones(base.shape[:2], dtype=np.float32),
        blend=RegionBlend(fabric=0.40),
    )
    assert np.array_equal(master[120:320, 360:460], base[120:320, 360:460])
    assert not np.array_equal(master[16:416, 16:216], base[16:416, 16:216])


@pytest.mark.tier1
@pytest.mark.f6
def test_f6_cli_screen_roi_drift_enforces_roi_separation(
    tmp_path: Path, fabric_and_hardware_1x: np.ndarray, run_cli: Any
) -> None:
    base = make_bicubic_4x(fabric_and_hardware_1x)
    cand = make_enhanced_4x(fabric_and_hardware_1x)
    base_p = save_rgb_png(base, tmp_path / "base.png")
    cand_p = save_rgb_png(cand, tmp_path / "cand.png")
    rois_p = tmp_path / "rois.json"
    rois_p.write_text(
        json.dumps([{"id": "hw", "kind": "hardware", "policy": "preserve", "rect": [360, 120, 100, 200]}]),
        encoding="utf-8",
    )

    clean_proc = run_cli(
        "scripts/screen-roi-drift.py",
        ["--base", str(base_p), "--candidate", str(cand_p), "--master", str(base_p), "--rois-json", str(rois_p), "--fail-on-drift"],
    )
    assert clean_proc.returncode == 0

    bad_master = base.copy()
    bad_master[150, 400] = [0, 255, 0]
    bad_p = save_rgb_png(bad_master, tmp_path / "bad_master.png")
    bad_proc = run_cli(
        "scripts/screen-roi-drift.py",
        ["--base", str(base_p), "--candidate", str(cand_p), "--master", str(bad_p), "--rois-json", str(rois_p), "--fail-on-drift"],
    )
    assert bad_proc.returncode == 1


# ===========================================================================
# F7: Pluggable Restoration Model Runner
# ===========================================================================


@pytest.mark.tier1
@pytest.mark.f7
def test_f7_unified_runner_interface_exists_in_engine() -> None:
    import fidelis.engine.runner as runner_mod

    assert hasattr(runner_mod, "RestorationRunner") or hasattr(runner_mod, "create_restoration_runner")


@pytest.mark.tier1
@pytest.mark.f7
def test_f7_imported_runner_loads_exact_grid_4x_with_provenance(
    tmp_path: Path, crema_and_rim_1x: np.ndarray
) -> None:
    from fidelis.engine.runner import ImportedRestorationRunner

    enh_4x = make_enhanced_4x(crema_and_rim_1x)
    imp_path = save_rgb_png(enh_4x, tmp_path / "imported_4x.png")

    runner = ImportedRestorationRunner(model_id="test-imported-v1")
    output_rgb, provenance = runner.run(crema_and_rim_1x, imported_path=imp_path, scale=4)
    assert output_rgb.shape == (512, 512, 3)
    assert output_rgb.dtype == np.uint8
    assert np.array_equal(output_rgb, enh_4x)
    assert provenance["model_id"] == "test-imported-v1"
    assert provenance["backend"] == "imported"
    assert provenance.get("weights_sha256") == "imported" or provenance.get("output_sha256") == sha256_file(imp_path)


@pytest.mark.tier1
@pytest.mark.f7
def test_f7_runner_rejects_mismatched_dimensions_without_silent_resize(
    tmp_path: Path, crema_and_rim_1x: np.ndarray
) -> None:
    from fidelis.engine.runner import ImportedRestorationRunner

    wrong_size = np.zeros((500, 500, 3), dtype=np.uint8)
    imp_path = save_rgb_png(wrong_size, tmp_path / "wrong_4x.png")
    runner = ImportedRestorationRunner(model_id="test-imported-v1")

    with pytest.raises(ValueError):
        runner.run(crema_and_rim_1x, imported_path=imp_path, scale=4)


@pytest.mark.tier1
@pytest.mark.f7
def test_f7_runner_supports_pluggable_callable_backend(crema_and_rim_1x: np.ndarray) -> None:
    from fidelis.engine.runner import CallableRestorationRunner

    runner = CallableRestorationRunner(
        model_id="deterministic-enhanced-stub",
        fn=lambda src, scale: make_enhanced_4x(src, scale=scale),
    )
    output_rgb, provenance = runner.run(crema_and_rim_1x, scale=4)
    assert output_rgb.shape == (512, 512, 3)
    assert provenance["model_id"] == "deterministic-enhanced-stub"
    assert "backend" in provenance


@pytest.mark.tier1
@pytest.mark.f7
def test_f7_optional_ml_runtimes_report_cleanly_when_absent() -> None:
    from fidelis.engine.runner import list_available_backends

    backends = list_available_backends()
    assert isinstance(backends, dict)
    assert "imported" in backends
    assert backends["imported"]["available"] is True


# ===========================================================================
# F8: Model-vs-Bicubic Audition Harness
# ===========================================================================


@pytest.mark.tier1
@pytest.mark.f8
def test_f8_audition_harness_runs_candidate_plus_texture_guard_vs_bicubic(
    tmp_path: Path, crema_and_rim_1x: np.ndarray
) -> None:
    from fidelis.studio.audition import run_model_vs_bicubic_audition

    rois = [
        {"id": "crema", "kind": "background", "policy": "texture_allowed", "rect": [36, 36, 56, 56]},
        {"id": "rim", "kind": "hardware", "policy": "preserve", "rect": [10, 10, 20, 20]},
    ]
    report = run_model_vs_bicubic_audition(
        source_rgb=crema_and_rim_1x,
        candidate_4x_rgb=make_enhanced_4x(crema_and_rim_1x),
        rois=rois,
        output_dir=tmp_path / "audition",
        case_id="crema-audition",
    )
    assert report["verdict"] in ("PASS", "FAIL")
    assert "metrics" in report
    assert "bicubic_path" in report
    assert "guarded_candidate_path" in report


@pytest.mark.tier1
@pytest.mark.f8
def test_f8_audition_emits_100_and_200_pct_side_by_side_crops(
    tmp_path: Path, crema_and_rim_1x: np.ndarray
) -> None:
    from fidelis.studio.audition import run_model_vs_bicubic_audition

    out_dir = tmp_path / "audition_crops"
    report = run_model_vs_bicubic_audition(
        source_rgb=crema_and_rim_1x,
        candidate_4x_rgb=make_enhanced_4x(crema_and_rim_1x),
        rois=[{"id": "crema", "kind": "background", "policy": "texture_allowed", "rect": [36, 36, 56, 56]}],
        output_dir=out_dir,
        case_id="crema-crops",
    )
    assert Path(report["html_report_path"]).is_file()
    html = Path(report["html_report_path"]).read_text(encoding="utf-8")
    assert "100%" in html and "200%" in html
    assert len(report.get("crops", [])) >= 1


@pytest.mark.tier1
@pytest.mark.f8
def test_f8_audition_fails_smoothed_and_oversharpened_candidates(
    tmp_path: Path, crema_and_rim_1x: np.ndarray
) -> None:
    from fidelis.studio.audition import run_model_vs_bicubic_audition

    rois = [{"id": "crema", "kind": "background", "policy": "texture_allowed", "rect": [36, 36, 56, 56]}]
    rep_smooth = run_model_vs_bicubic_audition(
        source_rgb=crema_and_rim_1x,
        candidate_4x_rgb=make_smoothed_4x(crema_and_rim_1x, sigma=2.5),
        rois=rois,
        output_dir=tmp_path / "smooth",
        case_id="smooth",
    )
    rep_over = run_model_vs_bicubic_audition(
        source_rgb=crema_and_rim_1x,
        candidate_4x_rgb=make_oversharpened_4x(crema_and_rim_1x, amount=2.8),
        rois=rois,
        output_dir=tmp_path / "over",
        case_id="over",
    )
    assert rep_smooth["verdict"] == "FAIL"
    assert rep_over["verdict"] == "FAIL"


@pytest.mark.tier1
@pytest.mark.f8
def test_f8_audition_passes_faithful_enhanced_candidate(
    tmp_path: Path, crema_and_rim_1x: np.ndarray
) -> None:
    from fidelis.studio.audition import run_model_vs_bicubic_audition

    rois = [{"id": "crema", "kind": "background", "policy": "texture_allowed", "rect": [36, 36, 56, 56]}]
    rep = run_model_vs_bicubic_audition(
        source_rgb=crema_and_rim_1x,
        candidate_4x_rgb=make_enhanced_4x(crema_and_rim_1x, detail_gain=12.0),
        rois=rois,
        output_dir=tmp_path / "good",
        case_id="good",
    )
    assert rep["verdict"] == "PASS"


@pytest.mark.tier1
@pytest.mark.f8
def test_f8_audition_generates_blind_review_manifest(
    tmp_path: Path, crema_and_rim_1x: np.ndarray
) -> None:
    from fidelis.studio.audition import run_model_vs_bicubic_audition

    out_dir = tmp_path / "blind"
    report = run_model_vs_bicubic_audition(
        source_rgb=crema_and_rim_1x,
        candidate_4x_rgb=make_enhanced_4x(crema_and_rim_1x),
        rois=[],
        output_dir=out_dir,
        case_id="blind-case",
        emit_blind_review=True,
    )
    assert Path(report["blind_ballot_path"]).is_file()
    assert Path(report["blind_answer_key_path"]).is_file()


# ===========================================================================
# F9: Coffee 1000x1000 Regression Case
# ===========================================================================


@pytest.mark.tier1
@pytest.mark.f9
def test_f9_coffee_regression_manifest_and_source_configured(product_edges_real_path: Path) -> None:
    src = load_rgb_png(product_edges_real_path)
    assert src.shape == (250, 250, 3)

    coffee_manifest_path = REPO_ROOT / "config" / "benchmark" / "coffee-regression.json"
    assert coffee_manifest_path.is_file(), "Coffee 1000x1000 regression manifest must exist"
    manifest = json.loads(coffee_manifest_path.read_text(encoding="utf-8"))
    case = manifest["cases"][0]
    assert case["target_dimensions"] == [1000, 1000]
    roi_ids = {r["id"] for r in case["rois"]}
    assert "coffee_crema" in roi_ids


@pytest.mark.tier1
@pytest.mark.f9
def test_f9_coffee_bicubic_1000x1000_baseline(product_edges_real_path: Path) -> None:
    src = load_rgb_png(product_edges_real_path)
    bic_1000 = make_bicubic_4x(src, target_size=(1000, 1000))
    assert bic_1000.shape == (1000, 1000, 3)


@pytest.mark.tier1
@pytest.mark.f9
def test_f9_coffee_smoothed_1000x1000_fails_regression(
    tmp_path: Path, product_edges_real_path: Path
) -> None:
    from fidelis.studio.audition import run_model_vs_bicubic_audition

    src = load_rgb_png(product_edges_real_path)
    coffee_manifest = json.loads(
        (REPO_ROOT / "config" / "benchmark" / "coffee-regression.json").read_text(encoding="utf-8")
    )
    rois = coffee_manifest["cases"][0]["rois"]
    rep = run_model_vs_bicubic_audition(
        source_rgb=src,
        candidate_4x_rgb=make_smoothed_4x(src, sigma=2.4, target_size=(1000, 1000)),
        rois=rois,
        output_dir=tmp_path / "coffee_smooth",
        case_id="coffee-1000-smooth",
    )
    assert rep["verdict"] == "FAIL"


@pytest.mark.tier1
@pytest.mark.f9
def test_f9_coffee_oversharpened_1000x1000_fails_regression(
    tmp_path: Path, product_edges_real_path: Path
) -> None:
    from fidelis.studio.audition import run_model_vs_bicubic_audition

    src = load_rgb_png(product_edges_real_path)
    coffee_manifest = json.loads(
        (REPO_ROOT / "config" / "benchmark" / "coffee-regression.json").read_text(encoding="utf-8")
    )
    rois = coffee_manifest["cases"][0]["rois"]
    rep = run_model_vs_bicubic_audition(
        source_rgb=src,
        candidate_4x_rgb=make_oversharpened_4x(src, amount=2.6, target_size=(1000, 1000)),
        rois=rois,
        output_dir=tmp_path / "coffee_over",
        case_id="coffee-1000-over",
    )
    assert rep["verdict"] == "FAIL"


@pytest.mark.tier1
@pytest.mark.f9
def test_f9_coffee_enhanced_1000x1000_with_texture_guard_passes(
    tmp_path: Path, product_edges_real_path: Path
) -> None:
    from fidelis.studio.audition import run_model_vs_bicubic_audition

    src = load_rgb_png(product_edges_real_path)
    coffee_manifest = json.loads(
        (REPO_ROOT / "config" / "benchmark" / "coffee-regression.json").read_text(encoding="utf-8")
    )
    rois = coffee_manifest["cases"][0]["rois"]
    rep = run_model_vs_bicubic_audition(
        source_rgb=src,
        candidate_4x_rgb=make_enhanced_4x(src, detail_gain=10.0, target_size=(1000, 1000)),
        rois=rois,
        output_dir=tmp_path / "coffee_pass",
        case_id="coffee-1000-pass",
    )
    assert rep["verdict"] == "PASS"


# ===========================================================================
# F10: Melato Fabric & Hardware Evaluation Protocol
# ===========================================================================


@pytest.mark.tier1
@pytest.mark.f10
def test_f10_melato_protocol_and_manifest_schema_exists() -> None:
    melato_cfg = REPO_ROOT / "config" / "benchmark" / "melato-protocol.json"
    assert melato_cfg.is_file(), "Melato evaluation protocol config must exist"
    data = json.loads(melato_cfg.read_text(encoding="utf-8"))
    assert "fabric" in data.get("required_roi_kinds", [])
    assert "seam" in data.get("required_roi_kinds", [])
    assert "hardware" in data.get("required_roi_kinds", [])


@pytest.mark.tier1
@pytest.mark.f10
def test_f10_melato_fashion_fabric_real_800x800_audition(
    tmp_path: Path, fashion_fabric_real_path: Path
) -> None:
    from fidelis.studio.audition import run_model_vs_bicubic_audition

    src = load_rgb_png(fashion_fabric_real_path)
    assert src.shape == (200, 200, 3)
    rois = [{"id": "weave", "kind": "fabric", "policy": "texture_allowed", "rect": [20, 20, 160, 160]}]
    rep = run_model_vs_bicubic_audition(
        source_rgb=src,
        candidate_4x_rgb=make_enhanced_4x(src, detail_gain=10.0, target_size=(800, 800)),
        rois=rois,
        output_dir=tmp_path / "melato_800",
        case_id="melato-fabric-800",
    )
    assert rep["verdict"] == "PASS"


@pytest.mark.tier1
@pytest.mark.f10
def test_f10_melato_sharpening_only_fails_protocol(
    tmp_path: Path, fashion_fabric_real_path: Path
) -> None:
    from fidelis.studio.audition import run_model_vs_bicubic_audition

    src = load_rgb_png(fashion_fabric_real_path)
    rois = [{"id": "weave", "kind": "fabric", "policy": "texture_allowed", "rect": [20, 20, 160, 160]}]
    rep = run_model_vs_bicubic_audition(
        source_rgb=src,
        candidate_4x_rgb=make_oversharpened_4x(src, amount=2.5, target_size=(800, 800)),
        rois=rois,
        output_dir=tmp_path / "melato_sharp",
        case_id="melato-sharp-fail",
    )
    assert rep["verdict"] == "FAIL"


@pytest.mark.tier1
@pytest.mark.f10
def test_f10_melato_imported_gpu_comfyui_4x_runner_accepted(
    tmp_path: Path, fashion_fabric_real_path: Path
) -> None:
    from fidelis.engine.runner import ImportedRestorationRunner
    from fidelis.studio.audition import run_model_vs_bicubic_audition

    src = load_rgb_png(fashion_fabric_real_path)
    imp_path = save_rgb_png(
        make_enhanced_4x(src, detail_gain=10.0, target_size=(800, 800)),
        tmp_path / "comfy_melato_4x.png",
    )
    runner = ImportedRestorationRunner(model_id="melato-comfyui-flux-4x")
    cand_4x, prov = runner.run(src, imported_path=imp_path, scale=4)
    assert prov["backend"] == "imported"
    rep = run_model_vs_bicubic_audition(
        source_rgb=src,
        candidate_4x_rgb=cand_4x,
        rois=[{"id": "weave", "kind": "fabric", "policy": "texture_allowed", "rect": [20, 20, 160, 160]}],
        output_dir=tmp_path / "melato_imported",
        case_id="melato-imported",
    )
    assert rep["verdict"] == "PASS"


@pytest.mark.tier1
@pytest.mark.f10
def test_f10_melato_quality_acceptance_rejects_hardware_mutation() -> None:
    from fidelis.eval.quality_acceptance import evaluate_held_out_acceptance

    base_submission = {
        "schema_version": "fidelis.quality_acceptance.v1",
        "calibration_summary": {"recipe_frozen": True, "case_ids": []},
        "automated_metrics": {
            "interior_texture_passed": True,
            "oversharpen_restraint_passed": True,
            "fabric_weave_passed": True,
            "hardware_seam_passed": True,
        },
        "reproducibility_receipt": {
            "code_sha": "abc123",
            "corpus_lock_sha256": "def456",
            "calibration_recipe_sha256": "ghi789",
            "runtime_versions": {"python": "3.11"},
            "model_weight_hashes": {"melato": "sha256:000"},
            "seed_policy": "fixed",
            "colour_path": "srgb",
        },
        "held_out_ballots": [
            {
                "case_id": f"{cat}-{i:02d}",
                "split": "held_out",
                "category": cat,
                "comparator": "bicubic",
                "outcome": "fidelis_win",
                "critical_defects": (["seam_zipper_hardware_mutation"] if (cat == "textile" and i == 1) else []),
            }
            for cat in ("portrait", "model_apparel", "textile", "macro", "packshot_edge")
            for i in range(1, 7)
        ],
    }
    res = evaluate_held_out_acceptance(base_submission)
    assert res["quantitative_gates_passed"] is False
    assert res["overall_status"] == "failed"
    assert "critical_fidelity_defects_present" in res["blocking_reasons"]
    assert res["critical_defect_count"] >= 1
