"""F10: Melato fabric, stitching/seam, and hardware evaluation protocol tests."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from fidelis.engine.restoration_runner import (
    _normalize_rois_for_guard,
    create_restoration_runner,
)
from fidelis.eval.corpus_manifest import audit
from fidelis.eval.quality_acceptance import (
    AcceptanceThresholds,
    evaluate_held_out_acceptance,
)
from fidelis.postprocess.roi_protection import build_roi_protection_masks
from fidelis.studio.audition import run_model_vs_bicubic_audition

REPO_ROOT = Path(__file__).resolve().parent.parent
MELATO_PROTOCOL_PATH = REPO_ROOT / "config" / "benchmark" / "melato-protocol.json"
MELATO_CORPUS_TEMPLATE_PATH = REPO_ROOT / "config" / "benchmark" / "melato-corpus-template-v1.json"
PROTOCOL_V1_PATH = REPO_ROOT / "config" / "benchmark" / "protocol-v1.json"
SLOTS_V1_PATH = REPO_ROOT / "config" / "benchmark" / "slots-v1.json"
FABRIC_SOURCE_PATH = REPO_ROOT / "experiments" / "eval_crops" / "fashion_fabric_real.png"
MELATO_CLI_PATH = REPO_ROOT / "scripts" / "audition-melato.py"


def _load_rgb(path: Path) -> np.ndarray:
    with Image.open(path) as img:
        return np.asarray(img.convert("RGB"), dtype=np.uint8)


def _bicubic_4x(src_rgb: np.ndarray, target_wh: tuple[int, int] = (800, 800)) -> np.ndarray:
    return np.asarray(
        Image.fromarray(src_rgb).resize(target_wh, Image.Resampling.BICUBIC),
        dtype=np.uint8,
    )


def _make_texture_enhanced_4x(bic_rgb: np.ndarray, gain: float = 0.35) -> np.ndarray:
    f = bic_rgb.astype(np.float32)
    low = cv2.GaussianBlur(f, (0, 0), sigmaX=1.2, sigmaY=1.2)
    vlow = cv2.GaussianBlur(f, (0, 0), sigmaX=3.2, sigmaY=3.2)
    return np.clip(np.rint(f + gain * (low - vlow)), 0, 255).astype(np.uint8)


def test_melato_protocol_and_corpus_template_valid() -> None:
    proto_melato = json.loads(MELATO_PROTOCOL_PATH.read_text(encoding="utf-8"))
    assert proto_melato["schema_version"] == 1
    assert proto_melato["id"] == "melato-fabric-hardware-v1"
    assert proto_melato["base_protocol_id"] == "fidelis-photo-corpus-v1"
    assert proto_melato["required_roi_kinds"] == ["fabric", "seam", "hardware"]
    assert proto_melato["roi_policies"] == {
        "fabric": "texture_allowed",
        "seam": "preserve",
        "hardware": "preserve",
    }
    assert proto_melato["comparator_baseline"] == "bicubic"
    assert proto_melato["scale"] == 4

    proto_v1 = json.loads(PROTOCOL_V1_PATH.read_text(encoding="utf-8"))
    slots_v1 = json.loads(SLOTS_V1_PATH.read_text(encoding="utf-8"))
    melato_corpus = json.loads(MELATO_CORPUS_TEMPLATE_PATH.read_text(encoding="utf-8"))

    audit_report = audit(melato_corpus, proto_v1, slots_v1, REPO_ROOT)
    assert audit_report["regression_available"] >= 1
    assert audit_report.get("errors") is None
    case_audit = audit_report["cases"][0]
    assert case_audit["id"] == "melato-smoke-fashion-fabric-800"
    assert "source_missing" not in case_audit["blockers"]
    assert "source_fingerprint_changed" not in case_audit["blockers"]
    assert "roi_outside_source" not in case_audit["blockers"]


def test_melato_roi_separation_at_800x800() -> None:
    src = _load_rgb(FABRIC_SOURCE_PATH)
    assert src.shape == (200, 200, 3)
    bic = _bicubic_4x(src, (800, 800))

    proto_melato = json.loads(MELATO_PROTOCOL_PATH.read_text(encoding="utf-8"))
    smoke = proto_melato["smoke_fixture"]
    target_rois = _normalize_rois_for_guard(
        smoke["rois"],
        source_shape=(200, 200),
        target_shape=(800, 800),
        roi_space=smoke["roi_space"],
    )
    masks, receipt = build_roi_protection_masks(bic, target_rois, use_sobel_heuristic=True)
    assert set(receipt["hard_contour_roi_ids"]) == {"melato_seam", "melato_hardware"}
    assert set(receipt["interior_texture_roi_ids"]) == {"melato_fabric"}
    assert receipt["sobel_suppressed_in_interior_texture"] is True

    roi_map = {r["id"]: r for r in target_rois}
    fx, fy, fw, fh = roi_map["melato_fabric"]["rect"]
    assert np.all(masks["interior_texture"][fy : fy + fh, fx : fx + fw] == 1.0)
    assert np.all(masks["edge_guard"][fy : fy + fh, fx : fx + fw] == 0.0)

    for hard_id in ("melato_seam", "melato_hardware"):
        hx, hy, hw, hh = roi_map[hard_id]["rect"]
        assert np.all(masks["hard_contour"][hy : hy + hh, hx : hx + hw] == 1.0)
        assert np.all(masks["protected"][hy : hy + hh, hx : hx + hw] == 1.0)


def test_melato_audition_pass_and_smooth_fail(tmp_path: Path) -> None:
    src = _load_rgb(FABRIC_SOURCE_PATH)
    bic = _bicubic_4x(src, (800, 800))
    proto_melato = json.loads(MELATO_PROTOCOL_PATH.read_text(encoding="utf-8"))
    smoke = dict(proto_melato["smoke_fixture"])

    # 1. Texture-preserving enhancement passes
    enhanced = _make_texture_enhanced_4x(bic, gain=0.35)
    enh_path = tmp_path / "melato-enhanced.png"
    Image.fromarray(enhanced).save(enh_path, format="PNG")
    runner_pass = create_restoration_runner(
        "imported",
        file_map={smoke["id"]: enh_path},
        model_id="melato_enhanced_test",
    )
    pass_report = run_model_vs_bicubic_audition(
        [smoke],
        runner_pass,
        output_dir=tmp_path / "melato_pass",
        asset_root=REPO_ROOT,
        apply_texture_guard=True,
        generate_html=False,
    )
    assert pass_report["summary"]["all_passed"] is True
    assert pass_report["cases"][0]["outcome"]["outcome"] == "PASS_MATERIAL_DETAIL"
    assert pass_report["cases"][0]["drift_report"]["locked_pixel_mismatches"] == 0
    assert Path(pass_report["blind"]["ballot_path"]).is_file()

    # 2. Smoothed output fails with FAIL_SMOOTHING_REGRESSION
    smoothed = cv2.GaussianBlur(bic, (0, 0), sigmaX=2.4, sigmaY=2.4)
    smooth_path = tmp_path / "melato-smoothed.png"
    Image.fromarray(smoothed).save(smooth_path, format="PNG")
    runner_fail = create_restoration_runner(
        "imported",
        file_map={smoke["id"]: smooth_path},
        model_id="melato_smoothed_test",
    )
    fail_report = run_model_vs_bicubic_audition(
        [smoke],
        runner_fail,
        output_dir=tmp_path / "melato_fail",
        asset_root=REPO_ROOT,
        apply_texture_guard=True,
        generate_html=False,
    )
    assert fail_report["summary"]["all_passed"] is False
    assert fail_report["cases"][0]["outcome"]["outcome"] == "FAIL_SMOOTHING_REGRESSION"


def test_melato_cli_and_acceptance_integration(tmp_path: Path) -> None:
    out_dir = tmp_path / "cli_smoke"
    proc = subprocess.run(
        [
            sys.executable,
            str(MELATO_CLI_PATH),
            "--smoke",
            "--backend",
            "bicubic",
            "--output-dir",
            str(out_dir),
            "--evaluate-acceptance",
            "--no-html",
        ],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=True,
    )
    cli_out = json.loads(proc.stdout)
    assert cli_out["protocol_id"] == "melato-fabric-hardware-v1"
    assert cli_out["summary"]["all_passed"] is True
    assert Path(cli_out["report"]).is_file()
    assert Path(cli_out["blind_ballot"]).is_file()
    assert Path(cli_out["blind_answer_key"]).is_file()
    assert Path(cli_out["acceptance_summary"]).is_file()

    # Verify evaluate_held_out_acceptance automated detail gate integration directly
    acceptance = json.loads(Path(cli_out["acceptance_summary"]).read_text(encoding="utf-8"))
    assert "automated_f2_texture_regression" not in acceptance["blocking_reasons"]
    assert "automated_f3_oversharpening_failed" not in acceptance["blocking_reasons"]
    assert "automated_f4_fabric_or_hardware_failed" not in acceptance["blocking_reasons"]
    assert acceptance["overall_status"] == "blocked_incomplete_evidence"
