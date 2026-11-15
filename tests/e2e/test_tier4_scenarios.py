"""Tier 4 E2E Tests: Comprehensive Real-World Scenarios (>= 4 end-to-end workflows)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from tests.e2e.conftest import (
    REPO_ROOT,
    build_single_case_manifest,
    load_rgb_png,
    make_bicubic_4x,
    make_enhanced_4x,
    make_oversharpened_4x,
    make_smoothed_4x,
    save_rgb_png,
)


@pytest.mark.tier4
@pytest.mark.f1
@pytest.mark.f2
@pytest.mark.f3
@pytest.mark.f5
@pytest.mark.f6
@pytest.mark.f8
@pytest.mark.f9
def test_t4_coffee_1000x1000_full_regression_scenario(
    tmp_path: Path, product_edges_real_path: Path
) -> None:
    """End-to-end Coffee 1000x1000 regression: smoothed fails, sharpened-only fails, guarded enhanced passes."""
    from fidelis.postprocess.regions import RegionBlend, compose_regions
    from fidelis.postprocess.roi_protection import build_roi_protection_masks, screen_internal_drift
    from fidelis.studio.audition import run_model_vs_bicubic_audition

    src_250 = load_rgb_png(product_edges_real_path)
    assert src_250.shape == (250, 250, 3)

    coffee_manifest = json.loads(
        (REPO_ROOT / "config" / "benchmark" / "coffee-regression.json").read_text(encoding="utf-8")
    )
    case = coffee_manifest["cases"][0]
    rois_1x = case["rois"]
    rois_4x = [
        {**r, "rect": [v * 4 for v in r["rect"]]} for r in rois_1x
    ]

    bic_1000 = make_bicubic_4x(src_250, target_size=(1000, 1000))
    smooth_1000 = make_smoothed_4x(src_250, sigma=2.4, target_size=(1000, 1000))
    over_1000 = make_oversharpened_4x(src_250, amount=2.6, target_size=(1000, 1000))
    enh_1000 = make_enhanced_4x(src_250, detail_gain=10.0, target_size=(1000, 1000))

    # Apply Texture Guard to enhanced output on 1000x1000 grid
    masks, _ = build_roi_protection_masks(bic_1000, rois_4x)
    guarded_1000, _ = compose_regions(
        bic_1000,
        enh_1000,
        fabric=np.ones((1000, 1000), dtype=np.float32),
        protected=masks["protected"],
        confidence=np.ones((1000, 1000), dtype=np.float32),
        blend=RegionBlend(fabric=0.8),
    )
    drift = screen_internal_drift(
        bic_1000, enh_1000, rois=rois_4x, protected=masks["protected"], master=guarded_1000
    )
    assert drift["locked_pixel_mismatches"] == 0
    assert drift["overall_verdict"] == "PASS"

    rep_smooth = run_model_vs_bicubic_audition(
        source_rgb=src_250,
        candidate_4x_rgb=smooth_1000,
        rois=rois_1x,
        output_dir=tmp_path / "coffee_smooth",
        case_id="coffee-smooth",
    )
    rep_over = run_model_vs_bicubic_audition(
        source_rgb=src_250,
        candidate_4x_rgb=over_1000,
        rois=rois_1x,
        output_dir=tmp_path / "coffee_over",
        case_id="coffee-over",
    )
    rep_pass = run_model_vs_bicubic_audition(
        source_rgb=src_250,
        candidate_4x_rgb=guarded_1000,
        rois=rois_1x,
        output_dir=tmp_path / "coffee_pass",
        case_id="coffee-pass",
        emit_blind_review=True,
    )

    assert rep_smooth["verdict"] == "FAIL"
    assert rep_over["verdict"] == "FAIL"
    assert rep_pass["verdict"] == "PASS"
    assert Path(rep_pass["html_report_path"]).is_file()
    assert Path(rep_pass["blind_ballot_path"]).is_file()


@pytest.mark.tier4
@pytest.mark.f1
@pytest.mark.f3
@pytest.mark.f4
@pytest.mark.f5
@pytest.mark.f6
@pytest.mark.f7
@pytest.mark.f8
@pytest.mark.f10
def test_t4_melato_fabric_and_hardware_audition_scenario(
    tmp_path: Path, fashion_fabric_real_path: Path
) -> None:
    """End-to-end Melato fabric/hardware audition: imported 4x GPU/ComfyUI outputs vs 4x bicubic."""
    from fidelis.engine.runner import ImportedRestorationRunner
    from fidelis.studio.audition import run_model_vs_bicubic_audition

    melato_cfg = json.loads(
        (REPO_ROOT / "config" / "benchmark" / "melato-protocol.json").read_text(encoding="utf-8")
    )
    assert "fabric" in melato_cfg["required_roi_kinds"]

    src_200 = load_rgb_png(fashion_fabric_real_path)
    assert src_200.shape == (200, 200, 3)

    rois_1x = [
        {"id": "fabric_main", "kind": "fabric", "policy": "texture_allowed", "rect": [10, 10, 140, 180]},
        {"id": "seam_edge", "kind": "seam", "policy": "preserve", "rect": [155, 10, 12, 180]},
        {"id": "hardware_buckle", "kind": "hardware", "policy": "preserve", "rect": [170, 40, 24, 80]},
    ]

    sharp_p = save_rgb_png(
        make_oversharpened_4x(src_200, amount=2.6, target_size=(800, 800)),
        tmp_path / "melato_sharp_800.png",
    )
    faithful_p = save_rgb_png(
        make_enhanced_4x(src_200, detail_gain=10.0, target_size=(800, 800)),
        tmp_path / "melato_faithful_800.png",
    )

    runner = ImportedRestorationRunner(model_id="melato-comfyui-candidate")
    sharp_800, _ = runner.run(src_200, imported_path=sharp_p, scale=4)
    faithful_800, prov = runner.run(src_200, imported_path=faithful_p, scale=4)
    assert prov["backend"] == "imported"

    rep_sharp = run_model_vs_bicubic_audition(
        source_rgb=src_200,
        candidate_4x_rgb=sharp_800,
        rois=rois_1x,
        output_dir=tmp_path / "melato_sharp",
        case_id="melato-sharp",
    )
    rep_faithful = run_model_vs_bicubic_audition(
        source_rgb=src_200,
        candidate_4x_rgb=faithful_800,
        rois=rois_1x,
        output_dir=tmp_path / "melato_faithful",
        case_id="melato-faithful",
        emit_blind_review=True,
    )

    assert rep_sharp["verdict"] == "FAIL"
    assert rep_faithful["verdict"] == "PASS"
    assert Path(rep_faithful["html_report_path"]).is_file()


@pytest.mark.tier4
@pytest.mark.f1
@pytest.mark.f5
@pytest.mark.f6
@pytest.mark.f8
@pytest.mark.f9
def test_t4_cli_end_to_end_comparators_drift_and_audition_pipeline(
    tmp_path: Path, product_edges_real_path: Path, run_cli: Any
) -> None:
    """Full CLI pipeline: run-comparators -> screen-roi-drift -> generate-audition-report -> summarize-blind."""
    src_250 = load_rgb_png(product_edges_real_path)
    asset_root = tmp_path / "assets"
    save_rgb_png(src_250, asset_root / "coffee.png")

    bic_1000 = make_bicubic_4x(src_250, target_size=(1000, 1000))
    enh_1000 = make_enhanced_4x(src_250, detail_gain=10.0, target_size=(1000, 1000))
    imp_dir = tmp_path / "imported_fidelis"
    save_rgb_png(enh_1000, imp_dir / "coffee-e2e.png")

    manifest = build_single_case_manifest(
        case_id="coffee-e2e",
        rel_source_path="coffee.png",
        category="macro",
        source_dimensions=[250, 250],
        target_dimensions=[1000, 1000],
        rois=[
            {"id": "crema", "kind": "background", "policy": "texture_allowed", "rect": [50, 50, 120, 120]},
            {"id": "rim", "kind": "hardware", "policy": "preserve", "rect": [10, 10, 30, 30]},
        ],
        asset_root=asset_root,
    )
    manifest_p = tmp_path / "manifest.json"
    manifest_p.write_text(json.dumps(manifest), encoding="utf-8")

    comp_out = tmp_path / "comp_out"
    p_comp = run_cli(
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
            "--blind-pair",
            "bicubic",
            "fidelis",
            "--blind-split",
            "regression",
        ],
    )
    assert p_comp.returncode == 0, p_comp.stderr

    # Screen ROI drift on bicubic base vs enhanced candidate
    base_p = save_rgb_png(bic_1000, tmp_path / "bic_1000.png")
    cand_p = save_rgb_png(enh_1000, tmp_path / "enh_1000.png")
    rois_4x_p = tmp_path / "rois_4x.json"
    rois_4x_p.write_text(
        json.dumps([{"id": "rim", "kind": "hardware", "policy": "preserve", "rect": [40, 40, 120, 120]}]),
        encoding="utf-8",
    )
    p_drift = run_cli(
        "scripts/screen-roi-drift.py",
        ["--base", str(base_p), "--candidate", str(cand_p), "--master", str(base_p), "--rois-json", str(rois_4x_p), "--fail-on-drift"],
    )
    assert p_drift.returncode == 0, p_drift.stderr

    # Generate audition HTML report
    html_p = tmp_path / "report.html"
    p_html = run_cli("scripts/generate-audition-report.py", [str(comp_out), "-o", str(html_p)])
    assert p_html.returncode == 0, p_html.stderr
    assert html_p.is_file()

    # Summarize blind ballot
    ballot = json.loads((comp_out / "blind-ballot.json").read_text(encoding="utf-8"))
    key = json.loads((comp_out / "blind-answer-key.json").read_text(encoding="utf-8"))
    for item in ballot["items"]:
        meta = key["mapping"][item["pair_id"]]
        item["choice"] = "left" if meta["left"] == "fidelis" else "right"
    completed_ballot_p = tmp_path / "completed_ballot.json"
    completed_ballot_p.write_text(json.dumps(ballot), encoding="utf-8")

    summary_p = tmp_path / "blind_summary.json"
    p_sum = run_cli(
        "scripts/run-comparators.py",
        [
            "summarize-blind",
            str(completed_ballot_p),
            str(comp_out / "blind-answer-key.json"),
            "--subject",
            "fidelis",
            "--target",
            "bicubic",
            "--output",
            str(summary_p),
        ],
    )
    assert p_sum.returncode == 0, p_sum.stderr
    summary = json.loads(summary_p.read_text(encoding="utf-8"))
    assert summary["sample_count"] == 1
    assert summary["win_rate"] == 1.0
    assert summary["preference_plus_tie_rate"] == 1.0
    assert summary["meets_proposed_thresholds"] is True


@pytest.mark.tier4
@pytest.mark.f5
@pytest.mark.f6
@pytest.mark.f7
@pytest.mark.f10
def test_t4_managed_export_16bit_and_held_out_acceptance_scenario(
    tmp_path: Path, fashion_fabric_real_path: Path
) -> None:
    """End-to-end 16-bit verified master export with ROI pixel locks + held-out acceptance pass."""
    from fidelis.engine.runner import ImportedRestorationRunner
    from fidelis.eval.quality_acceptance import evaluate_held_out_acceptance
    from fidelis.postprocess.managed_export import (
        ManagedImage,
        compose_managed_passes,
        export_verified_master,
        load_managed_pass,
    )
    from fidelis.postprocess.regions import RegionBlend
    from fidelis.postprocess.roi_protection import build_roi_protection_masks

    src_200 = load_rgb_png(fashion_fabric_real_path)
    base_800 = make_bicubic_4x(src_200, target_size=(800, 800))
    enh_800 = make_enhanced_4x(src_200, detail_gain=10.0, target_size=(800, 800))

    base_p = save_rgb_png(base_800, tmp_path / "base_800.png")
    imp_p = save_rgb_png(enh_800, tmp_path / "imp_800.png")

    runner = ImportedRestorationRunner(model_id="melato-prod-v1")
    cand_800, prov = runner.run(src_200, imported_path=imp_p, scale=4)
    assert prov["model_id"] == "melato-prod-v1"

    rois_800 = [
        {"id": "fab", "kind": "fabric", "policy": "texture_allowed", "rect": [40, 40, 560, 720]},
        {"id": "hw", "kind": "hardware", "policy": "preserve", "rect": [680, 160, 96, 320]},
    ]
    masks, _ = build_roi_protection_masks(base_800, rois_800)

    base_img = load_managed_pass(base_p)
    tex_img = ManagedImage(
        pixels=cand_800,
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
        fabric=np.ones((800, 800), dtype=np.float32),
        protected=masks["protected"],
        confidence=np.ones((800, 800), dtype=np.float32),
        blend=RegionBlend(fabric=0.45),
        bit_depth="16",
    )
    master_p, recipe_p, _ = export_verified_master(
        tmp_path / "melato_master_16bit.png",
        composed,
        meta,
        input_paths={"base": base_p, "texture": imp_p},
        profile="luxury_apparel",
    )
    assert master_p.is_file() and recipe_p.is_file()
    reloaded = load_managed_pass(master_p)
    assert reloaded.source_bit_depth == 16
    assert np.array_equal(
        reloaded.pixels[160:480, 680:776],
        base_800[160:480, 680:776].astype(np.uint16) * 257,
    )

    # Verify held-out quality acceptance gate passes for a clean Melato submission
    submission = {
        "schema_version": "fidelis.quality_acceptance.v1",
        "calibration_summary": {"recipe_frozen": True, "case_ids": []},
        "automated_metrics": {
            "interior_texture_passed": True,
            "oversharpen_restraint_passed": True,
            "fabric_weave_passed": True,
            "hardware_seam_passed": True,
        },
        "owner_creative_signoff": {
            "status": "approved",
            "reviewer": "creative-lead",
            "signed_at": "2026-11-14T00:00:00Z",
        },
        "reproducibility_receipt": {
            "code_sha": "deadbeef",
            "corpus_lock_sha256": "cafebabe",
            "calibration_recipe_sha256": "12345678",
            "runtime_versions": {"python": "3.11.2"},
            "model_weight_hashes": {"melato-prod-v1": prov.get("weights_sha256", "imported")},
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
                "critical_defects": [],
            }
            for cat in ("portrait", "model_apparel", "textile", "macro", "packshot_edge")
            for i in range(1, 7)
        ],
    }
    acc = evaluate_held_out_acceptance(submission)
    assert acc["quantitative_gates_passed"] is True
    assert acc["overall_status"] == "accepted"
