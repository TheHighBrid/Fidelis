"""Tier 3 E2E Tests: Cross-Feature Combinations across F1-F10 (>= 10 tests)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from tests.e2e.conftest import (
    REPO_ROOT,
    build_single_case_manifest,
    load_benchmark_protocol_and_slots,
    load_rgb_png,
    make_bicubic_4x,
    make_enhanced_4x,
    make_oversharpened_4x,
    make_smoothed_4x,
    save_rgb_png,
)


@pytest.mark.tier3
@pytest.mark.f1
@pytest.mark.f2
@pytest.mark.f3
def test_t3_f1_f2_f3_pipeline_ranks_enhanced_above_smoothed_and_oversharpened(
    crema_and_rim_1x: np.ndarray,
) -> None:
    from fidelis.eval.pipeline_metrics import measure_pipeline_metrics

    bic_4x = make_bicubic_4x(crema_and_rim_1x)
    smooth_4x = make_smoothed_4x(crema_and_rim_1x, sigma=2.4)
    over_4x = make_oversharpened_4x(crema_and_rim_1x, amount=2.8)
    enh_4x = make_enhanced_4x(crema_and_rim_1x, detail_gain=10.0)
    rois = [{"id": "crema", "kind": "background", "policy": "texture_allowed", "rect": [36, 36, 56, 56]}]

    m_smooth, _ = measure_pipeline_metrics(
        crema_and_rim_1x[:, :, ::-1], smooth_4x[:, :, ::-1], bicubic_bgr=bic_4x[:, :, ::-1], rois=rois
    )
    m_over, _ = measure_pipeline_metrics(
        crema_and_rim_1x[:, :, ::-1], over_4x[:, :, ::-1], bicubic_bgr=bic_4x[:, :, ::-1], rois=rois
    )
    m_enh, _ = measure_pipeline_metrics(
        crema_and_rim_1x[:, :, ::-1], enh_4x[:, :, ::-1], bicubic_bgr=bic_4x[:, :, ::-1], rois=rois
    )

    assert m_smooth["texture_retention_passed"] is False
    assert m_over["halo_restraint_passed"] is False
    assert m_enh["texture_retention_passed"] is True
    assert m_enh["halo_restraint_passed"] is True


@pytest.mark.tier3
@pytest.mark.f2
@pytest.mark.f5
@pytest.mark.f6
def test_t3_f2_f5_f6_texture_guard_locks_rim_and_preserves_crema_texture(
    crema_and_rim_1x: np.ndarray,
) -> None:
    from fidelis.eval.pipeline_metrics import measure_pipeline_metrics
    from fidelis.postprocess.regions import RegionBlend, compose_regions
    from fidelis.postprocess.roi_protection import build_roi_protection_masks, screen_internal_drift

    base = make_bicubic_4x(crema_and_rim_1x)
    tex = make_enhanced_4x(crema_and_rim_1x, detail_gain=5.0)
    rois_4x = [
        {"id": "crema", "kind": "background", "policy": "texture_allowed", "rect": [144, 144, 224, 224]},
        {"id": "spoon", "kind": "hardware", "policy": "preserve", "rect": [400, 80, 60, 350]},
    ]
    masks, _ = build_roi_protection_masks(base, rois_4x)
    master, _ = compose_regions(
        base,
        tex,
        fabric=np.ones(base.shape[:2], dtype=np.float32),
        protected=masks["protected"],
        confidence=np.ones(base.shape[:2], dtype=np.float32),
        blend=RegionBlend(fabric=0.8),
    )
    drift = screen_internal_drift(base, tex, rois=rois_4x, protected=masks["protected"], master=master)
    assert drift["locked_pixel_mismatches"] == 0
    assert drift["overall_verdict"] in ("PASS", "WARN")

    rois_1x = [{"id": "crema", "kind": "background", "policy": "texture_allowed", "rect": [36, 36, 56, 56]}]
    m, _ = measure_pipeline_metrics(
        crema_and_rim_1x[:, :, ::-1], master[:, :, ::-1], bicubic_bgr=base[:, :, ::-1], rois=rois_1x
    )
    assert m["interior_texture_retention_ratio"] >= 1.0
    assert m["texture_retention_passed"] is True


@pytest.mark.tier3
@pytest.mark.f3
@pytest.mark.f4
@pytest.mark.f5
@pytest.mark.f6
def test_t3_f3_f4_f5_f6_texture_guard_prevents_hardware_overshoot(
    fabric_and_hardware_1x: np.ndarray,
) -> None:
    from fidelis.eval.pipeline_metrics import measure_pipeline_metrics
    from fidelis.postprocess.regions import RegionBlend, compose_regions
    from fidelis.postprocess.roi_protection import build_roi_protection_masks

    base = make_bicubic_4x(fabric_and_hardware_1x)
    over = make_oversharpened_4x(fabric_and_hardware_1x, amount=2.8)
    rois_4x = [
        {"id": "fab", "kind": "fabric", "policy": "texture_allowed", "rect": [16, 16, 280, 464]},
        {"id": "seam", "kind": "seam", "policy": "preserve", "rect": [304, 16, 32, 464]},
        {"id": "hw", "kind": "hardware", "policy": "preserve", "rect": [360, 120, 112, 256]},
    ]
    masks, _ = build_roi_protection_masks(base, rois_4x)
    guarded, _ = compose_regions(
        base,
        over,
        fabric=np.ones(base.shape[:2], dtype=np.float32),
        protected=masks["protected"],
        confidence=np.ones(base.shape[:2], dtype=np.float32),
        blend=RegionBlend(fabric=0.8),
    )
    rois_1x = [
        {"id": "fab", "kind": "fabric", "policy": "texture_allowed", "rect": [4, 4, 70, 116]},
        {"id": "seam", "kind": "seam", "policy": "preserve", "rect": [76, 4, 8, 116]},
        {"id": "hw", "kind": "hardware", "policy": "preserve", "rect": [90, 30, 28, 64]},
    ]
    m, _ = measure_pipeline_metrics(
        fabric_and_hardware_1x[:, :, ::-1], guarded[:, :, ::-1], bicubic_bgr=base[:, :, ::-1], rois=rois_1x
    )
    assert m["hardware_faithfulness_passed"] is True
    assert m["seam_faithfulness_passed"] is True


@pytest.mark.tier3
@pytest.mark.f5
@pytest.mark.f6
@pytest.mark.f7
def test_t3_f5_f6_f7_imported_runner_plus_texture_guard_and_managed_export(
    tmp_path: Path, fabric_and_hardware_1x: np.ndarray
) -> None:
    from fidelis.engine.runner import ImportedRestorationRunner
    from fidelis.postprocess.managed_export import (
        ManagedImage,
        compose_managed_passes,
        export_verified_master,
        load_managed_pass,
    )
    from fidelis.postprocess.regions import RegionBlend
    from fidelis.postprocess.roi_protection import build_roi_protection_masks

    base_4x = make_bicubic_4x(fabric_and_hardware_1x)
    enh_4x = make_enhanced_4x(fabric_and_hardware_1x, detail_gain=10.0)
    base_p = save_rgb_png(base_4x, tmp_path / "base.png")
    imp_p = save_rgb_png(enh_4x, tmp_path / "imp.png")

    runner = ImportedRestorationRunner(model_id="t3-imported")
    cand_4x, prov = runner.run(fabric_and_hardware_1x, imported_path=imp_p, scale=4)
    assert prov["backend"] == "imported"

    rois_4x = [{"id": "hw", "kind": "hardware", "policy": "preserve", "rect": [360, 120, 112, 256]}]
    masks, _ = build_roi_protection_masks(base_4x, rois_4x)

    base_img = load_managed_pass(base_p)
    tex_img = ManagedImage(
        pixels=cand_4x,
        source_bit_depth=8,
        has_alpha=False,
        icc_profile=None,
        icc_description="sRGB",
        raw_orientation=1,
        normalized_orientation=False,
        source_format="PNG",
    )
    composed, _, meta = compose_managed_passes(
        base_img,
        tex_img,
        fabric=np.ones(base_4x.shape[:2], dtype=np.float32),
        protected=masks["protected"],
        confidence=np.ones(base_4x.shape[:2], dtype=np.float32),
        blend=RegionBlend(fabric=0.5),
    )
    master_p, recipe_p, _ = export_verified_master(
        tmp_path / "master.png",
        composed,
        meta,
        input_paths={"base": base_p, "texture": imp_p},
        profile="luxury_apparel",
    )
    assert master_p.is_file() and recipe_p.is_file()
    assert np.array_equal(load_rgb_png(master_p)[120:376, 360:472], base_4x[120:376, 360:472])


@pytest.mark.tier3
@pytest.mark.f1
@pytest.mark.f4
@pytest.mark.f7
@pytest.mark.f8
def test_t3_f1_f4_f7_f8_imported_runner_through_audition_harness(
    tmp_path: Path, fabric_and_hardware_1x: np.ndarray
) -> None:
    from fidelis.engine.runner import ImportedRestorationRunner
    from fidelis.studio.audition import run_model_vs_bicubic_audition

    imp_p = save_rgb_png(make_enhanced_4x(fabric_and_hardware_1x, detail_gain=9.0), tmp_path / "fab_4x.png")
    runner = ImportedRestorationRunner(model_id="t3-fab-runner")
    cand_4x, _ = runner.run(fabric_and_hardware_1x, imported_path=imp_p, scale=4)

    rois = [
        {"id": "fab", "kind": "fabric", "policy": "texture_allowed", "rect": [4, 4, 70, 116]},
        {"id": "seam", "kind": "seam", "policy": "preserve", "rect": [76, 4, 8, 116]},
        {"id": "hw", "kind": "hardware", "policy": "preserve", "rect": [90, 30, 28, 64]},
    ]
    rep = run_model_vs_bicubic_audition(
        source_rgb=fabric_and_hardware_1x,
        candidate_4x_rgb=cand_4x,
        rois=rois,
        output_dir=tmp_path / "audition",
        case_id="t3-fab-audition",
    )
    assert rep["verdict"] == "PASS"
    assert Path(rep["html_report_path"]).is_file()


@pytest.mark.tier3
@pytest.mark.f1
@pytest.mark.f5
@pytest.mark.f8
def test_t3_f1_f5_f8_cli_run_comparators_then_generate_audition_report(
    tmp_path: Path, crema_and_rim_1x: np.ndarray, run_cli: Any
) -> None:
    asset_root = tmp_path / "assets"
    save_rgb_png(crema_and_rim_1x, asset_root / "crema.png")
    imp_dir = tmp_path / "imported"
    save_rgb_png(make_enhanced_4x(crema_and_rim_1x), imp_dir / "t3-cli.png")

    manifest = build_single_case_manifest(
        case_id="t3-cli",
        rel_source_path="crema.png",
        category="macro",
        source_dimensions=[128, 128],
        target_dimensions=[512, 512],
        rois=[],
        asset_root=asset_root,
    )
    manifest_p = tmp_path / "manifest.json"
    manifest_p.write_text(json.dumps(manifest), encoding="utf-8")

    comp_out = tmp_path / "comp_out"
    p1 = run_cli(
        "scripts/run-comparators.py",
        [
            "run",
            str(manifest_p),
            "--root",
            str(asset_root),
            "--output-dir",
            str(comp_out),
            "--imported-dir",
            f"fidelis={imp_dir}",
            "--allow-regression-manifest",
        ],
    )
    assert p1.returncode == 0, p1.stderr

    html_out = tmp_path / "audition.html"
    p2 = run_cli("scripts/generate-audition-report.py", [str(comp_out), "-o", str(html_out)])
    assert p2.returncode == 0, p2.stderr
    assert html_out.is_file()
    html_text = html_out.read_text(encoding="utf-8")
    assert "100%" in html_text and "200%" in html_text


@pytest.mark.tier3
@pytest.mark.f2
@pytest.mark.f3
@pytest.mark.f5
@pytest.mark.f6
def test_t3_f2_f3_f5_f6_sobel_edge_guard_in_compose_regions_preserves_clean_edges(
    crema_and_rim_1x: np.ndarray,
) -> None:
    from fidelis.eval.pipeline_metrics import measure_pipeline_metrics
    from fidelis.postprocess.regions import RegionBlend, compose_regions
    from fidelis.postprocess.roi_protection import build_roi_protection_masks

    base = make_bicubic_4x(crema_and_rim_1x)
    tex = make_enhanced_4x(crema_and_rim_1x, detail_gain=12.0)
    masks, _ = build_roi_protection_masks(base, [], use_sobel_heuristic=True)
    master, _ = compose_regions(
        base,
        tex,
        fabric=np.ones(base.shape[:2], dtype=np.float32),
        protected=masks["protected"],
        edge_guard=masks["edge_guard"],
        confidence=np.ones(base.shape[:2], dtype=np.float32),
        blend=RegionBlend(fabric=0.65, edge_protection=0.85),
    )
    rois = [{"id": "crema", "kind": "background", "policy": "texture_allowed", "rect": [36, 36, 56, 56]}]
    m, _ = measure_pipeline_metrics(
        crema_and_rim_1x[:, :, ::-1], master[:, :, ::-1], bicubic_bgr=base[:, :, ::-1], rois=rois
    )
    assert m["texture_retention_passed"] is True
    assert m["halo_restraint_passed"] is True


@pytest.mark.tier3
@pytest.mark.f1
@pytest.mark.f8
@pytest.mark.f10
def test_t3_f1_f8_f10_blind_review_summary_and_quality_acceptance(
    tmp_path: Path, crema_and_rim_1x: np.ndarray
) -> None:
    from fidelis.eval.comparators import (
        build_blind_pairwise_manifest,
        make_imported_output_runner,
        run_comparators,
        summarize_blind_reviews,
    )

    asset_root = tmp_path / "assets"
    save_rgb_png(crema_and_rim_1x, asset_root / "c.png")
    imp_dir = tmp_path / "imp"
    save_rgb_png(make_enhanced_4x(crema_and_rim_1x), imp_dir / "c-01.png")

    manifest = build_single_case_manifest(
        case_id="c-01",
        rel_source_path="c.png",
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
    ballot, key = build_blind_pairwise_manifest(
        report, "bicubic", "fidelis", split="regression", blind_dir=tmp_path / "blind"
    )
    # Simulate blind reviewer choosing whichever side corresponds to fidelis
    for item in ballot["items"]:
        meta = key["mapping"][item["pair_id"]]
        item["choice"] = "left" if meta["left"] == "fidelis" else "right"

    summary = summarize_blind_reviews(ballot, key, subject_comparator="fidelis", target_comparator="bicubic")
    assert summary["sample_count"] == 1
    assert summary["win_rate"] == 1.0
    assert summary["preference_plus_tie_rate"] == 1.0
    assert summary["meets_proposed_thresholds"] is True


@pytest.mark.tier3
@pytest.mark.f4
@pytest.mark.f5
@pytest.mark.f6
def test_t3_f4_f5_f6_cli_screen_roi_drift_with_composed_fabric_master(
    tmp_path: Path, fabric_and_hardware_1x: np.ndarray, run_cli: Any
) -> None:
    from fidelis.postprocess.regions import RegionBlend, compose_regions
    from fidelis.postprocess.roi_protection import build_roi_protection_masks

    base = make_bicubic_4x(fabric_and_hardware_1x)
    tex = make_enhanced_4x(fabric_and_hardware_1x)
    rois = [
        {"id": "seam", "kind": "seam", "policy": "preserve", "rect": [304, 16, 32, 464]},
        {"id": "hw", "kind": "hardware", "policy": "preserve", "rect": [360, 120, 112, 256]},
    ]
    masks, _ = build_roi_protection_masks(base, rois)
    master, _ = compose_regions(
        base,
        tex,
        fabric=np.ones(base.shape[:2], dtype=np.float32),
        protected=masks["protected"],
        confidence=np.ones(base.shape[:2], dtype=np.float32),
        blend=RegionBlend(fabric=0.3),
    )

    base_p = save_rgb_png(base, tmp_path / "base.png")
    cand_p = save_rgb_png(tex, tmp_path / "cand.png")
    mast_p = save_rgb_png(master, tmp_path / "master.png")
    rois_p = tmp_path / "rois.json"
    rois_p.write_text(json.dumps(rois), encoding="utf-8")

    proc = run_cli(
        "scripts/screen-roi-drift.py",
        ["--base", str(base_p), "--candidate", str(cand_p), "--master", str(mast_p), "--rois-json", str(rois_p), "--fail-on-drift"],
    )
    assert proc.returncode == 0, proc.stderr


@pytest.mark.tier3
@pytest.mark.f7
@pytest.mark.f8
@pytest.mark.f9
def test_t3_f7_f8_f9_coffee_imported_runner_through_audition_harness(
    tmp_path: Path, product_edges_real_path: Path
) -> None:
    from fidelis.engine.runner import ImportedRestorationRunner
    from fidelis.studio.audition import run_model_vs_bicubic_audition

    src = load_rgb_png(product_edges_real_path)
    imp_p = save_rgb_png(
        make_enhanced_4x(src, detail_gain=10.0, target_size=(1000, 1000)),
        tmp_path / "coffee_imported_1000.png",
    )
    runner = ImportedRestorationRunner(model_id="coffee-imported-v1")
    cand_1000, prov = runner.run(src, imported_path=imp_p, scale=4)
    assert cand_1000.shape == (1000, 1000, 3)
    assert prov["model_id"] == "coffee-imported-v1"

    coffee_manifest = json.loads(
        (REPO_ROOT / "config" / "benchmark" / "coffee-regression.json").read_text(encoding="utf-8")
    )
    rep = run_model_vs_bicubic_audition(
        source_rgb=src,
        candidate_4x_rgb=cand_1000,
        rois=coffee_manifest["cases"][0]["rois"],
        output_dir=tmp_path / "coffee_audition",
        case_id="coffee-imported-audition",
    )
    assert rep["verdict"] == "PASS"
