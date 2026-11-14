"""F9: Coffee 1000x1000 regression tests using real product_edges_real.png."""

from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from fidelis.engine.restoration_runner import (
    _normalize_rois_for_guard,
    create_restoration_runner,
)
from fidelis.eval.detail_metrics import measure_scale_matched_metrics
from fidelis.postprocess.regions import RegionBlend, compose_regions
from fidelis.postprocess.roi_protection import build_roi_protection_masks
from fidelis.studio.audition import run_model_vs_bicubic_audition

REPO_ROOT = Path(__file__).resolve().parent.parent
COFFEE_MANIFEST_PATH = REPO_ROOT / "config" / "benchmark" / "coffee-regression.json"
COFFEE_SOURCE_PATH = REPO_ROOT / "experiments" / "eval_crops" / "product_edges_real.png"


def _load_rgb(path: Path) -> np.ndarray:
    with Image.open(path) as img:
        return np.asarray(img.convert("RGB"), dtype=np.uint8)


def _bicubic_4x(src_rgb: np.ndarray, target_wh: tuple[int, int] = (1000, 1000)) -> np.ndarray:
    return np.asarray(
        Image.fromarray(src_rgb).resize(target_wh, Image.Resampling.BICUBIC),
        dtype=np.uint8,
    )


def _make_smoothed_4x(bic_rgb: np.ndarray, sigma: float = 2.4) -> np.ndarray:
    return cv2.GaussianBlur(bic_rgb, (0, 0), sigmaX=sigma, sigmaY=sigma)


def _make_oversharpened_4x(bic_rgb: np.ndarray, amount: float = 2.8) -> np.ndarray:
    """Strong unsharp mask that creates contour haloing/overshoot."""
    f = bic_rgb.astype(np.float32)
    blur = cv2.GaussianBlur(f, (0, 0), sigmaX=1.8, sigmaY=1.8)
    sharp = f + amount * (f - blur)
    return np.clip(np.rint(sharp), 0, 255).astype(np.uint8)


def _make_texture_enhanced_4x(bic_rgb: np.ndarray, gain: float = 0.35) -> np.ndarray:
    """Subtle mid-band detail enhancement (difference of Gaussians in mid-band)."""
    f = bic_rgb.astype(np.float32)
    low = cv2.GaussianBlur(f, (0, 0), sigmaX=1.2, sigmaY=1.2)
    vlow = cv2.GaussianBlur(f, (0, 0), sigmaX=3.2, sigmaY=3.2)
    midband = low - vlow
    enhanced = f + gain * midband
    return np.clip(np.rint(enhanced), 0, 255).astype(np.uint8)


def test_coffee_manifest_and_source_geometry() -> None:
    src = _load_rgb(COFFEE_SOURCE_PATH)
    assert src.shape == (250, 250, 3)

    manifest = json.loads(COFFEE_MANIFEST_PATH.read_text(encoding="utf-8"))
    assert manifest["schema_version"] == 1
    case = manifest["cases"][0]
    assert case["role"] == "regression"
    assert case["category"] == "packshot_edge"
    assert case["split"] == "held_out"
    assert case["target_dimensions"] == [1000, 1000]
    assert case["roi_space"] in ("source", "auto")

    roi_by_id = {r["id"]: r for r in case["rois"]}
    assert {"coffee_crema", "cup_rim", "spoon_hardware"}.issubset(roi_by_id.keys())
    assert roi_by_id["coffee_crema"]["kind"] == "crema"
    assert roi_by_id["coffee_crema"]["policy"] == "texture_allowed"
    assert roi_by_id["cup_rim"]["kind"] == "hardware"
    assert roi_by_id["cup_rim"]["policy"] == "preserve"
    assert roi_by_id["spoon_hardware"]["kind"] == "hardware"
    assert roi_by_id["spoon_hardware"]["policy"] == "preserve"


def test_coffee_roi_protection_mask_separation_at_1000x1000() -> None:
    src = _load_rgb(COFFEE_SOURCE_PATH)
    bic = _bicubic_4x(src, (1000, 1000))
    manifest = json.loads(COFFEE_MANIFEST_PATH.read_text(encoding="utf-8"))
    case = manifest["cases"][0]

    target_rois = _normalize_rois_for_guard(
        case["rois"],
        source_shape=(250, 250),
        target_shape=(1000, 1000),
        roi_space=case["roi_space"],
    )
    masks, receipt = build_roi_protection_masks(bic, target_rois, use_sobel_heuristic=True)
    assert set(receipt["hard_contour_roi_ids"]) == {"cup_rim", "spoon_hardware"}
    assert set(receipt["interior_texture_roi_ids"]) == {"coffee_crema"}
    assert receipt["sobel_suppressed_in_interior_texture"] is True

    roi_map = {r["id"]: r for r in target_rois}
    cx, cy, cw, ch = roi_map["coffee_crema"]["rect"]
    assert cw == 520 and ch == 248
    # Crema interior must be marked interior_texture and have Sobel edge_guard suppressed
    assert np.all(masks["interior_texture"][cy : cy + ch, cx : cx + cw] == 1.0)
    assert np.all(masks["edge_guard"][cy : cy + ch, cx : cx + cw] == 0.0)
    assert np.all(masks["protected"][cy : cy + ch, cx : cx + cw] == 0.0)

    # Hard contours (cup_rim and spoon_hardware) must be strictly protected == 1.0
    for hard_id in ("cup_rim", "spoon_hardware"):
        hx, hy, hw, hh = roi_map[hard_id]["rect"]
        assert np.all(masks["hard_contour"][hy : hy + hh, hx : hx + hw] == 1.0)
        assert np.all(masks["protected"][hy : hy + hh, hx : hx + hw] == 1.0)


def test_coffee_smoothing_regression_fails_with_f2(tmp_path: Path) -> None:
    src = _load_rgb(COFFEE_SOURCE_PATH)
    bic = _bicubic_4x(src, (1000, 1000))
    smoothed = _make_smoothed_4x(bic, sigma=2.4)

    manifest = json.loads(COFFEE_MANIFEST_PATH.read_text(encoding="utf-8"))
    case = dict(manifest["cases"][0])
    cand_path = tmp_path / "coffee-smoothed-4x.png"
    Image.fromarray(smoothed).save(cand_path, format="PNG")

    runner = create_restoration_runner(
        "imported",
        file_map={case["id"]: cand_path},
        model_id="coffee_smoothed_test",
    )
    report = run_model_vs_bicubic_audition(
        [case],
        runner,
        output_dir=tmp_path / "audition_smooth",
        asset_root=REPO_ROOT,
        apply_texture_guard=True,
        generate_html=False,
    )
    assert report["summary"]["all_passed"] is False
    c_rep = report["cases"][0]
    assert c_rep["outcome"]["outcome"] == "FAIL_SMOOTHING_REGRESSION"
    assert c_rep["detail_metrics"]["interior_texture_passed"] is False


def test_coffee_sharpening_only_fails_with_f3(tmp_path: Path) -> None:
    src = _load_rgb(COFFEE_SOURCE_PATH)
    bic = _bicubic_4x(src, (1000, 1000))
    oversharp = _make_oversharpened_4x(bic, amount=2.8)

    manifest = json.loads(COFFEE_MANIFEST_PATH.read_text(encoding="utf-8"))
    case = dict(manifest["cases"][0])
    cand_path = tmp_path / "coffee-oversharp-4x.png"
    Image.fromarray(oversharp).save(cand_path, format="PNG")

    runner = create_restoration_runner(
        "imported",
        file_map={case["id"]: cand_path},
        model_id="coffee_oversharp_test",
    )
    report = run_model_vs_bicubic_audition(
        [case],
        runner,
        output_dir=tmp_path / "audition_oversharp",
        asset_root=REPO_ROOT,
        apply_texture_guard=False,
        generate_html=False,
    )
    assert report["summary"]["all_passed"] is False
    c_rep = report["cases"][0]
    assert c_rep["outcome"]["outcome"] == "FAIL_SHARPENING_ONLY"
    assert c_rep["detail_metrics"]["oversharpen_restraint_passed"] is False


def test_coffee_texture_preserving_enhancement_passes_end_to_end(tmp_path: Path) -> None:
    src = _load_rgb(COFFEE_SOURCE_PATH)
    bic = _bicubic_4x(src, (1000, 1000))
    enhanced_raw = _make_texture_enhanced_4x(bic, gain=0.35)

    manifest = json.loads(COFFEE_MANIFEST_PATH.read_text(encoding="utf-8"))
    case = dict(manifest["cases"][0])
    target_rois = _normalize_rois_for_guard(
        case["rois"],
        source_shape=(250, 250),
        target_shape=(1000, 1000),
        roi_space=case["roi_space"],
    )

    # Verify direct M2 compose_regions + M1 measure_scale_matched_metrics
    masks, _ = build_roi_protection_masks(bic, target_rois, use_sobel_heuristic=True)
    composed, _ = compose_regions(
        bic,
        enhanced_raw,
        fabric=masks["interior_texture"],
        protected=masks["protected"],
        edge_guard=masks["edge_guard"],
        interior_texture=masks["interior_texture"],
        blend=RegionBlend(fabric=1.0, edge_protection=0.5),
    )
    direct_metrics = measure_scale_matched_metrics(
        composed[:, :, ::-1],
        bic[:, :, ::-1],
        src[:, :, ::-1],
        rois=target_rois,
        roi_space="target",
    )
    assert direct_metrics["all_detail_gates_passed"] is True
    assert direct_metrics["interior_texture_passed"] is True
    assert direct_metrics["interior_texture"]["interior_texture_variance_ratio"] >= 1.0
    assert direct_metrics["interior_texture"]["interior_midband_energy_ratio"] >= 1.0

    # Verify full M3 run_model_vs_bicubic_audition with RestorationRunner + blind ballot + crops + HTML
    cand_path = tmp_path / "coffee-enhanced-4x.png"
    Image.fromarray(enhanced_raw).save(cand_path, format="PNG")
    runner = create_restoration_runner(
        "imported",
        file_map={case["id"]: cand_path},
        model_id="coffee_enhanced_test",
    )
    out_dir = tmp_path / "audition_pass"
    report = run_model_vs_bicubic_audition(
        [case],
        runner,
        output_dir=out_dir,
        asset_root=REPO_ROOT,
        apply_texture_guard=True,
        generate_html=True,
    )
    assert report["summary"]["all_passed"] is True
    c_rep = report["cases"][0]
    assert c_rep["outcome"]["outcome"] == "PASS_MATERIAL_DETAIL"
    assert c_rep["detail_metrics"]["all_detail_gates_passed"] is True
    assert c_rep["drift_report"]["locked_pixel_mismatches"] == 0

    # Verify audition_report.json, audition_report.html, blind ballot, and 100%/200% crops exist
    assert Path(report["report_json_path"]).is_file()
    assert Path(report["report_html_path"]).is_file()
    ballot_path = Path(report["blind"]["ballot_path"])
    key_path = Path(report["blind"]["answer_key_path"])
    assert ballot_path.is_file()
    assert key_path.is_file()

    ballot = json.loads(ballot_path.read_text(encoding="utf-8"))
    assert ballot["pair_count"] == 1
    assert len(ballot["items"]) == 1
    assert len(c_rep["crops"]) >= 2
    for crop in c_rep["crops"]:
        assert Path(crop["path"]).is_file()
