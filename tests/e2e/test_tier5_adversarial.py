"""Tier 5 White-Box Adversarial Tests for Fidelis M5 (Challengers 1 & 2)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from fidelis.engine.restoration_runner import (
    ImportedRestorationBackend,
    OnnxRestorationBackend,
    RestorationRunner,
)
from fidelis.engine.runner import ImportedRestorationRunner
from fidelis.eval.comparators import bicubic_runner, summarize_blind_reviews
from fidelis.eval.detail_metrics import (
    _normalize_rois_to_target,
    measure_fabric_hardware_faithfulness,
    measure_interior_texture_retention,
    measure_oversharpening_restraint,
    measure_scale_matched_metrics,
)
from fidelis.eval.pipeline_metrics import measure_pipeline_metrics
from fidelis.eval.quality_acceptance import (
    REQUIRED_CATEGORIES,
    evaluate_held_out_acceptance,
    validate_reproducibility_receipt,
)
from fidelis.postprocess.regions import RegionBlend, compose_regions
from fidelis.postprocess.roi_protection import (
    build_roi_protection_masks,
    screen_internal_drift,
)
from fidelis.studio.audition import (
    classify_audition_outcome,
    run_model_vs_bicubic_audition,
)
from tests.e2e.conftest import (
    REPO_ROOT,
    make_crema_and_rim_1x,
    make_oversharpened_4x,
    save_rgb_png,
)


def _valid_receipt() -> dict:
    return {
        "code_sha": "abc123",
        "corpus_lock_sha256": "def456",
        "calibration_recipe_sha256": "ghi789",
        "runtime_versions": {"python": "3.11"},
        "model_weight_hashes": {"model": "sha256:000"},
        "seed_policy": "fixed",
        "colour_path": "srgb",
    }


def _full_held_out_ballots(outcome: str = "fidelis_win", comparator: str = "bicubic") -> list[dict]:
    ballots = []
    for cat in REQUIRED_CATEGORIES:
        for i in range(6):
            ballots.append(
                {
                    "case_id": f"{cat}_{i}",
                    "split": "held_out",
                    "category": cat,
                    "comparator": comparator,
                    "outcome": outcome,
                }
            )
    return ballots


# ---------------------------------------------------------------------------
# Challenger 1: detail_metrics.py, pipeline_metrics.py, comparators.py, quality_acceptance.py
# ---------------------------------------------------------------------------


@pytest.mark.tier5
def test_adversarial_nan_and_inf_must_not_pass_f3_oversharpening() -> None:
    bic = np.full((64, 64, 3), 128.0, dtype=np.float32)
    cand_nan = bic.copy()
    cand_nan[10, 10, 0] = np.nan

    res_nan = measure_scale_matched_metrics(cand_nan, bic, input_color_order="rgb")
    assert res_nan["status"] != "measured" or res_nan["oversharpen_restraint_passed"] is False

    cand_inf = bic.copy()
    cand_inf[10, 10, 0] = np.inf
    res_inf = measure_scale_matched_metrics(cand_inf, bic, input_color_order="rgb")
    assert res_inf["status"] != "measured" or res_inf["oversharpen_restraint_passed"] is False


@pytest.mark.tier5
def test_adversarial_out_of_bounds_and_negative_rois_not_clamped_into_image() -> None:
    oob = _normalize_rois_to_target(
        [{"id": "oob", "kind": "fabric", "rect": [2000, 2000, 50, 50]}],
        (128, 128),
        roi_space="target",
    )
    assert oob == [], f"Out-of-bounds ROI should be dropped, got {oob}"

    neg = _normalize_rois_to_target(
        [{"id": "neg", "kind": "fabric", "rect": [-100, -100, 20, 20]}],
        (128, 128),
        roi_space="target",
    )
    assert neg == [], f"Off-screen negative ROI should be dropped, got {neg}"


@pytest.mark.tier5
def test_adversarial_protected_mask_enforced_without_hw_seam_rois() -> None:
    master = np.full((64, 64, 3), 128, dtype=np.uint8)
    cand = master.copy()
    cand[0:16, 0:16] = 255
    protected = np.ones((64, 64), dtype=np.float32)

    f4 = measure_fabric_hardware_faithfulness(
        cand, master, rois=[], protected=protected, master_rgb=master
    )
    assert f4["locked_pixel_mismatches"] > 0
    assert f4["hardware_seam_passed"] is False
    assert f4["passed"] is False


@pytest.mark.tier5
def test_adversarial_float64_bgr_matches_rgb_handling() -> None:
    img = np.full((64, 64, 3), 128.0, dtype=np.float64)
    res_rgb = measure_scale_matched_metrics(img, img, input_color_order="rgb")
    res_bgr = measure_scale_matched_metrics(img, img, input_color_order="bgr")
    assert res_bgr["status"] == res_rgb["status"]


@pytest.mark.tier5
def test_adversarial_small_texture_roi_smoothed_must_not_pass_via_whole_image_fallback() -> None:
    rng = np.random.default_rng(7)
    bic = rng.integers(80, 180, (128, 128, 3), dtype=np.uint8)
    cand = bic.copy()
    cand[10:16, 10:16] = 130  # completely flat inside 6x6 ROI
    cand[40:100, 40:100] = np.clip(
        bic[40:100, 40:100].astype(int) + rng.integers(-25, 25, (60, 60, 3)), 0, 255
    ).astype(np.uint8)

    res = measure_interior_texture_retention(
        cand,
        bic,
        rois=[{"id": "tiny_tex", "kind": "crema", "policy": "texture_allowed", "rect": [10, 10, 6, 6]}],
    )
    assert res["passed"] is False


@pytest.mark.tier5
def test_adversarial_oversharpening_restraint_respects_rois_scope() -> None:
    bic = np.full((64, 64, 3), 100, dtype=np.uint8)
    bic[:, 32:] = 200
    cand = bic.copy()
    # Oversharpen only around the vertical edge at x=32
    cand[:, 30:32] = 60
    cand[:, 32:34] = 240

    # ROI on flat left region [0, 0, 20, 64] should pass; ROI covering edge [24, 0, 16, 64] should fail
    flat_roi_res = measure_oversharpening_restraint(
        cand, bic, rois=[{"id": "flat", "kind": "fabric", "rect": [0, 0, 20, 64]}]
    )
    edge_roi_res = measure_oversharpening_restraint(
        cand, bic, rois=[{"id": "edge", "kind": "hardware", "rect": [24, 0, 16, 64]}]
    )
    assert flat_roi_res["passed"] is True
    assert edge_roi_res["passed"] is False


@pytest.mark.tier5
def test_adversarial_empty_0x0_image_returns_unavailable_without_crashing() -> None:
    empty = np.zeros((0, 0, 3), dtype=np.uint8)
    res = measure_scale_matched_metrics(empty, empty, input_color_order="rgb")
    assert res["status"] == "unavailable"
    assert res["all_detail_gates_passed"] is False


@pytest.mark.tier5
def test_adversarial_pipeline_metrics_float32_source_with_empty_rois() -> None:
    src = np.full((16, 16, 3), 128.0, dtype=np.float32)
    out = np.full((64, 64, 3), 128.0, dtype=np.float32)
    metrics, context = measure_pipeline_metrics(src, out, rois=[])
    assert context["status"] in ("measured", "unavailable")


@pytest.mark.tier5
def test_adversarial_pipeline_metrics_separates_hardware_and_seam_faithfulness() -> None:
    ref = np.full((64, 64, 3), 128, dtype=np.uint8)
    ref[:, 32:] = 200
    cand = ref.copy()
    # Introduce overshoot only in the seam ROI [24, 0, 16, 64], with no hardware ROI
    cand[:, 30:32] = 40
    cand[:, 32:34] = 250
    rois = [{"id": "s1", "kind": "seam", "policy": "preserve", "rect": [24, 0, 16, 64]}]
    metrics, context = measure_pipeline_metrics(
        ref, cand, bicubic_bgr=ref, rois=rois, roi_space="target", input_color_order="rgb"
    )
    assert context["status"] == "measured"
    assert metrics["seam_faithfulness_passed"] is False
    assert metrics["hardware_faithfulness_passed"] is True


@pytest.mark.tier5
def test_adversarial_bicubic_runner_reject_without_target_dimensions(tmp_path: Path) -> None:
    res = bicubic_runner(
        {"id": "malformed-neg", "expected_behavior": "reject_unsupported_input"},
        tmp_path / "missing.png",
        tmp_path / "out.png",
    )
    assert res.status == "rejected_unsupported"


@pytest.mark.tier5
def test_adversarial_summarize_blind_reviews_rejects_duplicate_pair_ids() -> None:
    key_doc = {
        "mapping": {
            "pair_001": {"left": "fidelis", "right": "bicubic", "category": "macro"},
            "pair_002": {"left": "fidelis", "right": "bicubic", "category": "macro"},
        }
    }
    ballot = {
        "items": [{"pair_id": "pair_001", "choice": "left"}] * 10
        + [{"pair_id": "pair_002", "choice": "right"}]
    }
    with pytest.raises(ValueError):
        summarize_blind_reviews(ballot, key_doc, subject_comparator="fidelis", target_comparator="bicubic")


@pytest.mark.tier5
def test_adversarial_calibration_whitespace_contamination_detected() -> None:
    sub = {
        "reproducibility_receipt": _valid_receipt(),
        "calibration_summary": {"recipe_frozen": True, "case_ids": [" portrait_0 "]},
        "held_out_ballots": _full_held_out_ballots(),
        "required_comparators": ["bicubic"],
    }
    report = evaluate_held_out_acceptance(sub)
    assert "portrait_0" in report["calibration"]["split_contamination_ids"]
    assert report["overall_status"] == "failed"


@pytest.mark.tier5
def test_adversarial_split_contamination_only_must_fail_not_blocked() -> None:
    sub = {
        "reproducibility_receipt": _valid_receipt(),
        "calibration_summary": {"recipe_frozen": True, "case_ids": ["c1"]},
        "held_out_ballots": [
            {
                "case_id": "c1",
                "split": "calibration",
                "category": "macro",
                "comparator": "bicubic",
                "outcome": "fidelis_win",
            }
        ],
        "required_comparators": ["bicubic"],
    }
    report = evaluate_held_out_acceptance(sub)
    assert report["overall_status"] == "failed"


@pytest.mark.tier5
def test_adversarial_duplicate_ballot_stuffing_must_not_pass() -> None:
    ballots = []
    for cat in REQUIRED_CATEGORIES:
        for i in range(5):
            ballots.append(
                {
                    "case_id": f"{cat}_{i}",
                    "split": "held_out",
                    "category": cat,
                    "comparator": "bicubic",
                    "outcome": "comparator_win",
                }
            )
        for _ in range(20):
            ballots.append(
                {
                    "case_id": f"{cat}_win",
                    "split": "held_out",
                    "category": cat,
                    "comparator": "bicubic",
                    "outcome": "fidelis_win",
                }
            )
    sub = {
        "reproducibility_receipt": _valid_receipt(),
        "calibration_summary": {"recipe_frozen": True, "case_ids": []},
        "held_out_ballots": ballots,
        "required_comparators": ["bicubic"],
    }
    report = evaluate_held_out_acceptance(sub)
    assert report["overall_status"] == "failed"


@pytest.mark.tier5
def test_adversarial_whitespace_receipt_fields_rejected() -> None:
    ws_receipt = {k: "   " for k in _valid_receipt()}
    check = validate_reproducibility_receipt(ws_receipt)
    assert check["complete"] is False


# ---------------------------------------------------------------------------
# Challenger 2: roi_protection.py, regions.py, restoration_runner.py, audition.py, audition-melato.py
# ---------------------------------------------------------------------------


@pytest.mark.tier5
def test_regions_uint16_srgb_linear_roundtrip_bit_exact() -> None:
    """Identical uint16 base/texture blended at alpha=0.5 must round-trip with zero quantization drift."""
    all16 = np.repeat(np.arange(65536, dtype=np.uint16)[:, None, None], 3, axis=2).reshape(256, 256, 3)
    res, _ = compose_regions(
        all16,
        all16,
        fabric=np.ones((256, 256), dtype=np.float32),
        confidence=np.ones((256, 256), dtype=np.float32),
        blend=RegionBlend(fabric=0.5),
    )
    assert np.array_equal(res, all16)


@pytest.mark.tier5
def test_batch_audition_catches_raw_oversharpening_under_texture_guard(tmp_path: Path) -> None:
    """Batch audition must not pass an oversharpened model merely because preserve ROIs mask its halos."""
    src = make_crema_and_rim_1x(64, 64, seed=42)
    over_4x = make_oversharpened_4x(src, amount=3.0)
    rois_target = [
        {"id": "crema", "kind": "crema", "policy": "texture_allowed", "override": None, "rect": [64, 64, 96, 96]},
        {"id": "rim", "kind": "hardware", "policy": "preserve", "override": None, "rect": [16, 16, 48, 224]},
    ]
    src_p = save_rgb_png(src, tmp_path / "src.png")
    save_rgb_png(over_4x, tmp_path / "imp" / "c1.png")
    runner = RestorationRunner(ImportedRestorationBackend(tmp_path / "imp"))

    batch_rep = run_model_vs_bicubic_audition(
        cases=[{"id": "c1", "source_path": str(src_p), "rois": rois_target, "roi_space": "target"}],
        runner=runner,
        output_dir=tmp_path / "batch",
        apply_texture_guard=True,
        generate_html=False,
    )
    assert batch_rep["cases"][0]["detail_metrics"]["oversharpen_restraint_passed"] is False
    assert batch_rep["cases"][0]["outcome"]["outcome"] == "FAIL_SHARPENING_ONLY"


@pytest.mark.tier5
def test_runner_unlock_override_not_negated_by_other_interior_texture_roi() -> None:
    """An explicitly unlocked hardware ROI must still receive candidate pixels even if a fabric ROI exists."""
    class _ConstBackend:
        model_id = "const"
        backend_name = "const"
        weights_sha256 = "const"

        def restore(self, source_rgb, *, base_4x, scale, target_shape, case_id=None):
            return np.full(target_shape, 200, dtype=np.uint8), {}

    src = np.full((16, 16, 3), 50, dtype=np.uint8)
    runner = RestorationRunner(_ConstBackend())
    res = runner.run(
        src,
        rois=[
            {"id": "hw_u", "kind": "hardware", "policy": "preserve", "override": "unlock", "rect": [0, 0, 32, 32]},
            {"id": "fab", "kind": "fabric", "policy": "texture_allowed", "override": None, "rect": [32, 32, 32, 32]},
        ],
        use_sobel_heuristic=False,
    )
    assert np.all(res.image[:32, :32] == 200)


@pytest.mark.tier5
def test_roi_overlap_preserve_then_unlock_clears_locked_ids_and_hard_contour() -> None:
    """Overlapping unlock override must remove the overridden ROI from locked_roi_ids and hard_contour."""
    base = np.zeros((64, 64, 3), dtype=np.uint8)
    rois = [
        {"id": "hw_preserve", "kind": "hardware", "policy": "preserve", "override": None, "rect": [0, 0, 32, 32]},
        {"id": "hw_unlock", "kind": "hardware", "policy": "preserve", "override": "unlock", "rect": [0, 0, 32, 32]},
    ]
    masks, receipt = build_roi_protection_masks(base, rois)
    assert "hw_preserve" not in receipt["locked_roi_ids"]
    assert float(masks["hard_contour"].max()) == 0.0


@pytest.mark.tier5
def test_drift_screen_exempts_texture_allowed_roi_from_coherence_fail() -> None:
    """A texture_allowed fabric ROI should not FAIL_DRIFT solely due to weave gradient reorientation."""
    base = np.zeros((64, 64, 3), dtype=np.uint8)
    base[:, ::4] = 255
    cand = np.zeros((64, 64, 3), dtype=np.uint8)
    cand[::4, :] = 255
    rois = [{"id": "fab1", "kind": "fabric", "policy": "texture_allowed", "override": None, "rect": [0, 0, 64, 64]}]
    rep = screen_internal_drift(base, cand, rois=rois)
    assert rep["roi_reports"][0]["status"] == "PASS"
    assert rep["overall_verdict"] == "PASS"


@pytest.mark.tier5
def test_drift_screen_evaluates_small_7x7_image() -> None:
    """Images smaller than 8x8 must still be evaluated rather than returning blocks_evaluated=0."""
    base = np.zeros((7, 7, 3), dtype=np.uint8)
    base[2:4, 2:4] = 255
    cand = np.zeros((7, 7, 3), dtype=np.uint8)
    cand[4:6, 4:6] = 255
    rep = screen_internal_drift(base, cand)
    assert rep["blocks_evaluated"] >= 1


@pytest.mark.tier5
def test_classify_audition_outcome_consistent_when_status_unavailable() -> None:
    """Non-measured metrics status must never yield outcome='PASS_MATERIAL_DETAIL'."""
    cls = classify_audition_outcome({"status": "unavailable", "all_detail_gates_passed": True})
    assert cls["passed"] is False
    assert cls["outcome"] != "PASS_MATERIAL_DETAIL"


@pytest.mark.tier5
def test_imported_backend_rejects_rgba_like_imported_runner(tmp_path: Path) -> None:
    """ImportedRestorationBackend must reject 4-channel RGBA PNGs rather than silently converting."""
    src = np.full((16, 16, 3), 100, dtype=np.uint8)
    rgba_p = tmp_path / "c1.png"
    Image.fromarray(np.full((64, 64, 4), 120, dtype=np.uint8)).save(rgba_p)

    with pytest.raises(ValueError):
        ImportedRestorationRunner().run(src, imported_path=rgba_p, scale=4)

    with pytest.raises(ValueError):
        RestorationRunner(ImportedRestorationBackend(tmp_path)).run(src, case_id="c1")


@pytest.mark.tier5
def test_onnx_backend_rejects_nan_output(tmp_path: Path) -> None:
    """Non-finite ONNX model outputs must raise ValueError instead of silently casting NaN to 0."""
    weights = tmp_path / "dummy.onnx"
    weights.write_bytes(b"dummy")

    class _FakeInput:
        name = "input"

    class _FakeSession:
        def get_inputs(self):
            return [_FakeInput()]

        def run(self, _, __):
            return [np.full((1, 3, 64, 64), np.nan, dtype=np.float32)]

    src = np.full((16, 16, 3), 100, dtype=np.uint8)
    be = OnnxRestorationBackend(weights, session=_FakeSession())
    with pytest.raises(ValueError):
        RestorationRunner(be).run(src, apply_texture_guard=False)


@pytest.mark.tier5
def test_audition_melato_cli_mismatched_backend_args_exits_cleanly(tmp_path: Path) -> None:
    """audition-melato.py should exit with code 2 (not unhandled TypeError traceback) on invalid backend args."""
    proc = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "audition-melato.py"),
            "--smoke",
            "--backend",
            "bicubic",
            "--imported-dir",
            str(tmp_path),
            "--output-dir",
            str(tmp_path / "out"),
        ],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 2
    assert "Traceback" not in proc.stderr


@pytest.mark.tier5
def test_audition_melato_tiny_4x4_image_default_roi_in_bounds(tmp_path: Path) -> None:
    """audition-melato.py --image on a 4x4 image must not produce an out-of-bounds default ROI."""
    tiny_p = save_rgb_png(np.full((4, 4, 3), 120, dtype=np.uint8), tmp_path / "tiny.png")
    out_dir = tmp_path / "out"
    proc = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "audition-melato.py"),
            "--image",
            str(tiny_p),
            "--backend",
            "bicubic",
            "--output-dir",
            str(out_dir),
            "--no-html",
        ],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
