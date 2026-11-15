"""Model-vs-4x-Bicubic audition harness, outcome classification, and crop generation."""

from __future__ import annotations

import base64
import html
import json
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

import numpy as np
from PIL import Image

from fidelis.engine.restoration_runner import (
    DimensionMismatchError,
    RestorationRunner,
    _bicubic_upscale,
    _enforce_exact_shape,
    _normalize_rois_for_guard,
    _validate_rgb_uint8,
)
from fidelis.eval.benchmark_suite import BenchmarkSuite
from fidelis.eval.comparators import build_blind_pairwise_manifest


def classify_audition_outcome(detail_metrics: Mapping[str, Any]) -> dict[str, Any]:
    """Classify M1 scale-matched 4x detail metrics into an explicit audition verdict."""
    status = str(detail_metrics.get("status", "unavailable"))
    interior_passed = bool(detail_metrics.get("interior_texture_passed", False))
    oversharpen_passed = bool(detail_metrics.get("oversharpen_restraint_passed", False))
    fabric_passed = bool(detail_metrics.get("fabric_weave_passed", False))
    hardware_passed = bool(detail_metrics.get("hardware_seam_passed", False))
    all_passed = bool(detail_metrics.get("all_detail_gates_passed", False))

    gate_summary = {
        "interior_texture": interior_passed,
        "oversharpen_restraint": oversharpen_passed,
        "fabric_weave": fabric_passed,
        "hardware_seam": hardware_passed,
    }

    failure_reasons: list[str] = []
    if status != "measured":
        reason = str(detail_metrics.get("reason") or f"metrics_status_{status}")
        failure_reasons.append(reason)
    if not interior_passed:
        it_reason = (detail_metrics.get("interior_texture") or {}).get("reason")
        failure_reasons.append(str(it_reason or "texture_smoothed_below_bicubic"))
    if not oversharpen_passed:
        os_reason = (detail_metrics.get("oversharpening_restraint") or {}).get("reason")
        failure_reasons.append(str(os_reason or "oversharpening_halo_ringing"))
    if not fabric_passed:
        failure_reasons.append("fabric_weave_unfaithful")
    if not hardware_passed:
        failure_reasons.append("hardware_seam_drift_or_ringing")

    if status != "measured":
        if not interior_passed and detail_metrics.get("interior_texture"):
            outcome = "FAIL_SMOOTHING_REGRESSION"
        else:
            outcome = "FAIL_UNAVAILABLE"
    elif all_passed:
        outcome = "PASS_MATERIAL_DETAIL"
    elif not interior_passed:
        outcome = "FAIL_SMOOTHING_REGRESSION"
    elif not oversharpen_passed:
        outcome = "FAIL_SHARPENING_ONLY"
    else:
        outcome = "FAIL_FAITHFULNESS"

    return {
        "outcome": outcome,
        "passed": bool(status == "measured" and all_passed),
        "failure_reasons": failure_reasons,
        "gate_summary": gate_summary,
    }


def generate_side_by_side_crops(
    candidate_rgb: np.ndarray,
    bicubic_rgb: np.ndarray,
    *,
    rois: Sequence[Mapping[str, Any]] = (),
    output_dir: str | Path,
    case_id: str,
    zoom_factors: Sequence[int] = (1, 2),
    source_shape: tuple[int, int] | None = None,
    roi_space: str = "target",
) -> list[dict[str, Any]]:
    """Generate native 100% and 200% pixel-exact side-by-side PNGs ([candidate | bicubic])."""
    cand = _validate_rgb_uint8(candidate_rgb, "candidate_rgb")
    bic = _enforce_exact_shape(bicubic_rgb, cand.shape, "bicubic_rgb")
    h, w, _ = cand.shape

    out_root = Path(output_dir) / "crops" / case_id
    out_root.mkdir(parents=True, exist_ok=True)

    src_hw = source_shape if source_shape is not None else (h, w)
    norm_rois = _normalize_rois_for_guard(
        rois, source_shape=src_hw, target_shape=(h, w), roi_space=roi_space
    )

    regions: list[tuple[str, str, list[int]]] = [("full_frame", "full_frame", [0, 0, w, h])]
    for roi in norm_rois:
        regions.append((roi["id"], roi["kind"], roi["rect"]))

    crops: list[dict[str, Any]] = []
    for region_id, region_kind, (rx, ry, rw, rh) in regions:
        cand_crop = cand[ry : ry + rh, rx : rx + rw]
        bic_crop = bic[ry : ry + rh, rx : rx + rw]
        pair_arr = np.concatenate([cand_crop, bic_crop], axis=1)
        pair_img = Image.fromarray(pair_arr)

        for zoom in zoom_factors:
            z = int(zoom)
            if z < 1:
                raise ValueError(f"zoom_factor must be >= 1, got {zoom}")
            if z == 1:
                zoomed_img = pair_img
            else:
                zoomed_img = pair_img.resize(
                    (pair_arr.shape[1] * z, pair_arr.shape[0] * z),
                    Image.Resampling.NEAREST,
                )
            crop_filename = f"{case_id}__{region_id}__{z * 100}pct.png"
            crop_path = out_root / crop_filename
            zoomed_img.save(crop_path, format="PNG")
            crops.append(
                {
                    "region": region_id,
                    "kind": region_kind,
                    "zoom": z,
                    "zoom_label": f"{z * 100}%",
                    "path": str(crop_path),
                    "width": int(zoomed_img.width),
                    "height": int(zoomed_img.height),
                    "rect": [int(rx), int(ry), int(rw), int(rh)],
                }
            )
    return crops


def _encode_png_b64(path: Path) -> str:
    if not path.is_file():
        return ""
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{data}"


def render_audition_html(report: Mapping[str, Any], output_html: str | Path) -> Path:
    """Render an audition_report.json payload into a self-contained HTML inspection report."""
    out_path = Path(output_html)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    summary = report.get("summary", {})
    cases = report.get("cases", [])

    case_cards = []
    for case in cases:
        outcome = case.get("outcome", {})
        verdict = str(outcome.get("outcome", "UNKNOWN"))
        passed = bool(outcome.get("passed", False))
        badge_bg = "#238636" if passed else "#da3633"
        prov = case.get("provenance", {})
        dm = case.get("detail_metrics", {})
        it = dm.get("interior_texture", {})
        os_r = dm.get("oversharpening_restraint", {})
        gates = outcome.get("gate_summary", {})

        crop_html = []
        for crop in case.get("crops", []):
            b64 = _encode_png_b64(Path(crop["path"]))
            if not b64:
                continue
            crop_html.append(
                f"""
                <div class="crop-card">
                  <div class="crop-hdr">
                    <strong>{html.escape(str(crop['region']))}</strong>
                    <span>{html.escape(str(crop['kind']))} &bull; {html.escape(str(crop['zoom_label']))} ({crop['width']}x{crop['height']})</span>
                  </div>
                  <div class="crop-img-wrap">
                    <img src="{b64}" alt="{html.escape(str(crop['region']))} {html.escape(str(crop['zoom_label']))}">
                  </div>
                </div>"""
            )

        case_cards.append(
            f"""
            <section class="case-section">
              <div class="case-header">
                <div>
                  <h2>Case: {html.escape(str(case.get('id', 'unknown')))}</h2>
                  <div class="muted">
                    Model: <code>{html.escape(str(prov.get('model_id', '')))}</code>
                    ({html.escape(str(prov.get('backend', '')))} / SHA-256: <code>{html.escape(str(prov.get('weights_sha256', ''))[:16])}</code>)
                    &bull; Texture Guard: <strong>{prov.get('texture_guard_applied')}</strong>
                  </div>
                </div>
                <span class="badge" style="background:{badge_bg}">{html.escape(verdict)}</span>
              </div>
              <div class="metrics-row">
                <div class="metric-box"><div class="m-lbl">Interior Texture Var Ratio</div><div class="m-val">{it.get('interior_texture_variance_ratio', 'N/A')}</div></div>
                <div class="metric-box"><div class="m-lbl">Interior Midband Ratio</div><div class="m-val">{it.get('interior_midband_energy_ratio', 'N/A')}</div></div>
                <div class="metric-box"><div class="m-lbl">Contour Overshoot p95</div><div class="m-val">{os_r.get('contour_overshoot_p95', 'N/A')}</div></div>
                <div class="metric-box"><div class="m-lbl">Gates (IT / OS / FW / HS)</div><div class="m-val">{gates.get('interior_texture')} / {gates.get('oversharpen_restraint')} / {gates.get('fabric_weave')} / {gates.get('hardware_seam')}</div></div>
              </div>
              <div class="crops-grid">
                {''.join(crop_html)}
              </div>
            </section>"""
        )

    html_doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Fidelis Visual Audition &amp; Benchmark Report</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #121417; color: #e6edf3; margin: 0; padding: 24px; }}
  .header {{ display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #30363d; padding-bottom: 16px; margin-bottom: 24px; }}
  .badge {{ color: #fff; padding: 4px 12px; border-radius: 12px; font-size: 13px; font-weight: 600; }}
  .muted {{ color: #8b949e; font-size: 13px; }}
  .case-section {{ background: #1c2026; border: 1px solid #30363d; border-radius: 8px; padding: 18px; margin-bottom: 24px; }}
  .case-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px; }}
  .metrics-row {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; margin-bottom: 16px; }}
  .metric-box {{ background: #161b22; border: 1px solid #30363d; border-radius: 6px; padding: 10px 12px; }}
  .m-lbl {{ color: #8b949e; font-size: 11px; text-transform: uppercase; }}
  .m-val {{ font-family: ui-monospace, SFMono-Regular, monospace; font-size: 15px; margin-top: 4px; }}
  .crops-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(360px, 1fr)); gap: 16px; }}
  .crop-card {{ background: #0d1117; border: 1px solid #30363d; border-radius: 6px; overflow: hidden; }}
  .crop-hdr {{ padding: 8px 12px; border-bottom: 1px solid #30363d; display: flex; justify-content: space-between; font-size: 12px; }}
  .crop-img-wrap {{ overflow: auto; padding: 8px; text-align: center; }}
  .crop-img-wrap img {{ max-width: 100%; height: auto; image-rendering: pixelated; }}
</style>
</head>
<body>
  <div class="header">
    <div>
      <h1>Fidelis Visual Audition &amp; Benchmark Report</h1>
      <div class="muted">Report Type: <strong>MODEL_VS_BICUBIC_AUDITION</strong> &bull; Left: Candidate+Guard | Right: 4x Bicubic</div>
    </div>
    <span class="badge" style="background:{'#238636' if summary.get('all_passed') else '#da3633'}">
      {summary.get('passed_cases', 0)}/{summary.get('total_cases', 0)} PASSED
    </span>
  </div>
  {''.join(case_cards)}
</body>
</html>
"""
    out_path.write_text(html_doc, encoding="utf-8")
    return out_path


class _InMemoryCandidateBackend:
    """In-memory backend wrapping a pre-computed 4x RGB array for single-case audition."""

    backend_name = "in_memory"
    weights_sha256 = "in_memory"

    def __init__(self, candidate_rgb: np.ndarray, model_id: str = "in_memory_candidate") -> None:
        self.candidate_rgb = candidate_rgb
        self.model_id = model_id

    def restore(
        self,
        source_rgb: np.ndarray,
        *,
        base_4x: np.ndarray,
        scale: int,
        target_shape: tuple[int, int, int],
        case_id: Optional[str] = None,
    ) -> tuple[np.ndarray, dict[str, Any]]:
        out = _enforce_exact_shape(self.candidate_rgb, target_shape, "candidate_4x_rgb")
        return out, {"in_memory": True}


def _run_single_case_audition(
    *,
    source_rgb: np.ndarray,
    candidate_4x_rgb: np.ndarray,
    rois: Sequence[Mapping[str, Any]],
    output_dir: str | Path,
    case_id: str,
    scale: int,
    roi_space: str,
    apply_texture_guard: bool,
    generate_html: bool,
    emit_blind_review: bool,
    blind_seed: int,
    blind_split: str,
) -> dict[str, Any]:
    from fidelis.eval.pipeline_metrics import measure_pipeline_metrics

    src = _validate_rgb_uint8(source_rgb, "source_rgb")
    if int(scale) < 1:
        raise ValueError(f"scale must be >= 1, got {scale}")
    sh, sw, _ = src.shape
    tw, th = sw * int(scale), sh * int(scale)
    cand = _enforce_exact_shape(candidate_4x_rgb, (th, tw, 3), "candidate_4x_rgb")

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    case_dir = out_dir / "cases" / case_id
    case_dir.mkdir(parents=True, exist_ok=True)

    bicubic_rgb = _bicubic_upscale(src, tw, th)
    target_rois = _normalize_rois_for_guard(
        rois, source_shape=(sh, sw), target_shape=(th, tw), roi_space=roi_space
    )

    runner = RestorationRunner(_InMemoryCandidateBackend(cand))
    result = runner.run(
        src,
        scale=int(scale),
        target_size=(tw, th),
        rois=target_rois,
        roi_space="target",
        apply_texture_guard=apply_texture_guard,
        case_id=case_id,
    )

    src_path = case_dir / "source_1x.png"
    cand_path = case_dir / "candidate_4x.png"
    bic_path = case_dir / "bicubic_4x.png"
    Image.fromarray(src).save(src_path, format="PNG")
    Image.fromarray(result.image).save(cand_path, format="PNG")
    Image.fromarray(bicubic_rgb).save(bic_path, format="PNG")

    suite = BenchmarkSuite()
    detail_metrics = suite.evaluate_4x_detail(
        src,
        result.image,
        bicubic_ref=bicubic_rgb,
        rois=target_rois,
        roi_space="target",
    )
    flat_metrics, _ = measure_pipeline_metrics(
        src[:, :, ::-1],
        result.image[:, :, ::-1],
        bicubic_bgr=bicubic_rgb[:, :, ::-1],
        rois=target_rois,
        roi_space="target",
    )

    from fidelis.eval.detail_metrics import measure_oversharpening_restraint
    raw_os = measure_oversharpening_restraint(cand, bicubic_rgb, rois=target_rois)
    if raw_os["passed"]:
        for r in target_rois:
            if r.get("policy") == "preserve" and r.get("override") != "unlock":
                rx, ry, rw, rh = r["rect"]
                if rw >= 8 and rh >= 8:
                    roi_os = measure_oversharpening_restraint(
                        cand[ry : ry + rh, rx : rx + rw],
                        bicubic_rgb[ry : ry + rh, rx : rx + rw],
                    )
                    if not roi_os["passed"]:
                        raw_os = roi_os
                        break
    if not raw_os["passed"]:
        detail_metrics["oversharpening_restraint"] = raw_os
        detail_metrics["oversharpen_restraint_passed"] = False
        detail_metrics["all_detail_gates_passed"] = False
        flat_metrics["edge_overshoot"] = float(raw_os["contour_overshoot_p95"])
        flat_metrics["nyquist_midband_ratio"] = float(raw_os["contour_nyquist_to_midband_ratio"])
        flat_metrics["halo_restraint_passed"] = False
        flat_metrics["all_detail_gates_passed"] = False

    outcome = classify_audition_outcome(detail_metrics)

    crops = generate_side_by_side_crops(
        result.image,
        bicubic_rgb,
        rois=target_rois,
        output_dir=case_dir,
        case_id=case_id,
        roi_space="target",
    )

    drift_summary = (
        {k: v for k, v in result.drift_report.items() if k != "drift_guard_mask"}
        if isinstance(result.drift_report, dict)
        else result.drift_report
    )
    verdict = "PASS" if outcome["passed"] else "FAIL"
    outcome_counts = {outcome["outcome"]: 1}
    case_entry = {
        "id": case_id,
        "split": blind_split,
        "category": "material_detail",
        "source_path": str(src_path),
        "candidate_path": str(cand_path),
        "bicubic_path": str(bic_path),
        "provenance": result.provenance.to_dict(),
        "guard_receipt": result.guard_receipt,
        "drift_report": drift_summary,
        "detail_metrics": detail_metrics,
        "outcome": outcome,
        "crops": crops,
    }
    report: dict[str, Any] = {
        "schema_version": 1,
        "report_type": "model_vs_bicubic_audition",
        "case_id": case_id,
        "verdict": verdict,
        "outcome": outcome,
        "metrics": flat_metrics,
        "detail_metrics": detail_metrics,
        "bicubic_path": str(bic_path),
        "guarded_candidate_path": str(cand_path),
        "crops": crops,
        "model": {
            "model_id": runner.backend.model_id,
            "backend": runner.backend.backend_name,
            "weights_sha256": runner.backend.weights_sha256,
            "apply_texture_guard": bool(apply_texture_guard),
        },
        "summary": {
            "total_cases": 1,
            "passed_cases": 1 if outcome["passed"] else 0,
            "failed_cases": 0 if outcome["passed"] else 1,
            "all_passed": bool(outcome["passed"]),
            "outcome_counts": outcome_counts,
        },
        "cases": [case_entry],
    }

    if emit_blind_review:
        compat_cases = [
            {
                "id": case_id,
                "case_id": case_id,
                "split": blind_split,
                "category": "material_detail",
                "source_path": str(src_path),
                "outputs": {
                    "candidate": {"status": "completed", "output_path": str(cand_path)},
                    "bicubic": {"status": "completed", "output_path": str(bic_path)},
                },
            }
        ]
        blind_dir = out_dir / "blind"
        ballot, answer_key = build_blind_pairwise_manifest(
            {"cases": compat_cases},
            "candidate",
            "bicubic",
            split=blind_split,
            seed=blind_seed,
            blind_dir=blind_dir,
        )
        blind_dir.mkdir(parents=True, exist_ok=True)
        ballot_path = blind_dir / "blind-ballot.json"
        key_path = blind_dir / "blind-answer-key.json"
        ballot_path.write_text(json.dumps(ballot, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        key_path.write_text(json.dumps(answer_key, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        report["blind"] = {
            "seed": blind_seed,
            "split": blind_split,
            "pair_count": int(ballot.get("pair_count", len(ballot.get("items", [])))),
            "ballot_path": str(ballot_path),
            "answer_key_path": str(key_path),
        }
        report["blind_ballot_path"] = str(ballot_path)
        report["blind_answer_key_path"] = str(key_path)

    report_json_path = out_dir / "audition_report.json"
    report_json_path.write_text(
        json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    report["report_json_path"] = str(report_json_path)

    if generate_html:
        html_path = render_audition_html(report, out_dir / "audition_report.html")
        report["report_html_path"] = str(html_path)
        report["html_report_path"] = str(html_path)

    return report


def run_model_vs_bicubic_audition(
    cases: Optional[Sequence[Mapping[str, Any]]] = None,
    runner: Optional[RestorationRunner] = None,
    *,
    output_dir: str | Path,
    blind_seed: int = 20261110,
    apply_texture_guard: bool = True,
    generate_html: bool = True,
    asset_root: str | Path | None = None,
    blind_split: str = "held_out",
    source_rgb: Optional[np.ndarray] = None,
    candidate_4x_rgb: Optional[np.ndarray] = None,
    rois: Sequence[Mapping[str, Any]] = (),
    case_id: str = "audition-case",
    emit_blind_review: bool = False,
    scale: int = 4,
    roi_space: str = "auto",
) -> dict[str, Any]:
    """Run candidate model (+ texture guard) vs deterministic 4x BICUBIC across cases or a single in-memory pair."""
    if source_rgb is not None or candidate_4x_rgb is not None:
        if source_rgb is None or candidate_4x_rgb is None:
            raise ValueError("Both source_rgb and candidate_4x_rgb are required for single-case audition")
        return _run_single_case_audition(
            source_rgb=source_rgb,
            candidate_4x_rgb=candidate_4x_rgb,
            rois=rois,
            output_dir=output_dir,
            case_id=case_id,
            scale=scale,
            roi_space=roi_space,
            apply_texture_guard=apply_texture_guard,
            generate_html=generate_html,
            emit_blind_review=emit_blind_review,
            blind_seed=blind_seed,
            blind_split=blind_split,
        )
    if cases is None or runner is None:
        raise ValueError("Batch audition requires both cases and runner")

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    root = Path(asset_root) if asset_root is not None else None
    suite = BenchmarkSuite()

    case_results: list[dict[str, Any]] = []
    compat_cases: list[dict[str, Any]] = []
    outcome_counts: dict[str, int] = {}

    for raw_case in cases:
        case_id = str(raw_case["id"])
        src_p = Path(raw_case["source_path"])
        if root is not None and not src_p.is_absolute():
            src_p = root / src_p
        with Image.open(src_p) as img:
            source_rgb = np.asarray(img.convert("RGB"), dtype=np.uint8)

        sh, sw, _ = source_rgb.shape
        scale = int(raw_case.get("scale", 4))
        td = raw_case.get("target_dimensions")
        if td is not None:
            tw, th = int(td[0]), int(td[1])
        else:
            tw, th = sw * scale, sh * scale

        bicubic_rgb = _bicubic_upscale(source_rgb, tw, th)
        roi_space = str(raw_case.get("roi_space", "auto"))
        raw_rois = raw_case.get("rois") or ()
        target_rois = _normalize_rois_for_guard(
            raw_rois, source_shape=(sh, sw), target_shape=(th, tw), roi_space=roi_space
        )

        result = runner.run(
            source_rgb,
            scale=scale,
            target_size=(tw, th),
            rois=target_rois,
            roi_space="target",
            apply_texture_guard=apply_texture_guard,
            case_id=case_id,
        )

        case_dir = out_dir / "cases" / case_id
        case_dir.mkdir(parents=True, exist_ok=True)
        cand_path = case_dir / "candidate_4x.png"
        bic_path = case_dir / "bicubic_4x.png"
        Image.fromarray(result.image).save(cand_path, format="PNG")
        Image.fromarray(bicubic_rgb).save(bic_path, format="PNG")

        detail_metrics = suite.evaluate_4x_detail(
            source_rgb,
            result.image,
            bicubic_ref=bicubic_rgb,
            rois=target_rois,
            roi_space="target",
        )
        from fidelis.eval.detail_metrics import measure_oversharpening_restraint
        raw_os = measure_oversharpening_restraint(result.raw_candidate, bicubic_rgb, rois=target_rois)
        for r in target_rois:
            if r.get("policy") == "preserve" and r.get("override") != "unlock":
                rx, ry, rw, rh = r["rect"]
                if rw >= 8 and rh >= 8:
                    roi_os = measure_oversharpening_restraint(
                        result.raw_candidate[ry : ry + rh, rx : rx + rw],
                        bicubic_rgb[ry : ry + rh, rx : rx + rw],
                    )
                    if roi_os["contour_overshoot_p95"] > raw_os["contour_overshoot_p95"]:
                        raw_os = roi_os
        severe_raw_os = (not raw_os["passed"]) and (
            raw_os["contour_overshoot_p95"] > 8.0
            or (
                raw_os["contour_nyquist_gain_vs_bicubic"] > 3.0
                and raw_os["contour_overshoot_mean"] > 0.5
            )
        )
        if severe_raw_os:
            detail_metrics["oversharpening_restraint"] = raw_os
            detail_metrics["oversharpen_restraint_passed"] = False
            detail_metrics["all_detail_gates_passed"] = False
        outcome = classify_audition_outcome(detail_metrics)
        verdict = outcome["outcome"]
        outcome_counts[verdict] = outcome_counts.get(verdict, 0) + 1

        crops = generate_side_by_side_crops(
            result.image,
            bicubic_rgb,
            rois=target_rois,
            output_dir=case_dir,
            case_id=case_id,
            roi_space="target",
        )

        split = str(raw_case.get("split", blind_split))
        category = str(raw_case.get("category", "material_detail"))

        drift_summary = (
            {k: v for k, v in result.drift_report.items() if k != "drift_guard_mask"}
            if isinstance(result.drift_report, dict)
            else result.drift_report
        )

        case_results.append(
            {
                "id": case_id,
                "split": split,
                "category": category,
                "source_path": str(src_p),
                "candidate_path": str(cand_path),
                "bicubic_path": str(bic_path),
                "provenance": result.provenance.to_dict(),
                "guard_receipt": result.guard_receipt,
                "drift_report": drift_summary,
                "detail_metrics": detail_metrics,
                "outcome": outcome,
                "crops": crops,
            }
        )
        compat_cases.append(
            {
                "id": case_id,
                "case_id": case_id,
                "split": split,
                "category": category,
                "source_path": str(src_p),
                "outputs": {
                    "candidate": {"status": "completed", "output_path": str(cand_path)},
                    "bicubic": {"status": "completed", "output_path": str(bic_path)},
                },
            }
        )

    blind_dir = out_dir / "blind"
    ballot, answer_key = build_blind_pairwise_manifest(
        {"cases": compat_cases},
        "candidate",
        "bicubic",
        split=blind_split,
        seed=blind_seed,
        blind_dir=blind_dir,
    )
    blind_dir.mkdir(parents=True, exist_ok=True)
    ballot_path = blind_dir / "blind-ballot.json"
    key_path = blind_dir / "blind-answer-key.json"
    ballot_path.write_text(json.dumps(ballot, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    key_path.write_text(json.dumps(answer_key, indent=2, allow_nan=False) + "\n", encoding="utf-8")

    passed_count = sum(1 for c in case_results if c["outcome"]["passed"])
    total_count = len(case_results)
    report: dict[str, Any] = {
        "schema_version": 1,
        "report_type": "model_vs_bicubic_audition",
        "model": {
            "model_id": runner.backend.model_id,
            "backend": runner.backend.backend_name,
            "weights_sha256": runner.backend.weights_sha256,
            "apply_texture_guard": bool(apply_texture_guard),
        },
        "summary": {
            "total_cases": total_count,
            "passed_cases": passed_count,
            "failed_cases": total_count - passed_count,
            "all_passed": total_count > 0 and passed_count == total_count,
            "outcome_counts": outcome_counts,
        },
        "blind": {
            "seed": blind_seed,
            "split": blind_split,
            "pair_count": int(ballot.get("pair_count", len(ballot.get("items", [])))),
            "ballot_path": str(ballot_path),
            "answer_key_path": str(key_path),
        },
        "cases": case_results,
    }

    report_json_path = out_dir / "audition_report.json"
    report_json_path.write_text(
        json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    report["report_json_path"] = str(report_json_path)

    if generate_html:
        html_path = render_audition_html(report, out_dir / "audition_report.html")
        report["report_html_path"] = str(html_path)

    return report
