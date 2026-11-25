"""Model-vs-4x-Bicubic audition harness, outcome classification, and crop generation."""

from __future__ import annotations

import base64
import hashlib
import html
import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from fidelis.engine.restoration_runner import (
    RestorationRunner,
    _bicubic_upscale,
    _enforce_exact_shape,
    _normalize_rois_for_guard,
    _validate_rgb_uint8,
)
from fidelis.eval.benchmark_suite import BenchmarkSuite
from fidelis.eval.comparators import build_blind_pairwise_manifest
from fidelis.postprocess.roi_protection import VALID_POLICIES, VALID_ROI_KINDS

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

_MANIFEST_ROI_TYPE_TO_KIND: dict[str, str] = {
    "identity_landmark": "identity",
    "skin_zone": "skin",
    "hair_edge": "hair",
    "garment_fit": "fabric",
    "textile_weave": "fabric",
    "logo": "logo",
    "text": "text",
    "care_label": "text",
    "zipper": "seam",
    "stitch": "seam",
    "hardware": "hardware",
    "background_edge": "background",
    "alpha_edge": "alpha_boundary",
    "shadow_rolloff": "shadow",
}


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


def _screened_audition_outcome(detail_metrics, drift_report):
    """Keep final-image geometry failures from becoming detail-only passes."""
    outcome = classify_audition_outcome(detail_metrics)
    if not isinstance(drift_report, dict):
        return outcome
    locked_mismatches = drift_report.get("locked_pixel_mismatches", 0)
    failed = drift_report.get("overall_verdict") == "FAIL" or locked_mismatches > 0
    outcome["gate_summary"]["geometry"] = not failed
    if failed:
        if outcome["passed"]:
            outcome["outcome"] = "FAIL_FAITHFULNESS"
        outcome["passed"] = False
        reason = "protected_pixel_mismatch" if locked_mismatches > 0 else "geometric_drift"
        outcome["failure_reasons"].append(reason)
    return outcome


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
    """Generate independent candidate and bicubic PNGs at native 100% and 200% zoom."""
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
        for zoom in zoom_factors:
            z = int(zoom)
            if z < 1:
                raise ValueError(f"zoom_factor must be >= 1, got {zoom}")
            dimensions = (rw * z, rh * z)
            paths = {}
            for role, pixels in (("candidate", cand_crop), ("bicubic", bic_crop)):
                image = Image.fromarray(pixels)
                if z != 1:
                    image = image.resize(dimensions, Image.Resampling.NEAREST)
                path = out_root / f"{case_id}__{region_id}__{z * 100}pct__{role}.png"
                image.save(path, format="PNG")
                paths[role] = str(path)
            crops.append(
                {
                    "region": region_id,
                    "kind": region_kind,
                    "zoom": z,
                    "zoom_label": f"{z * 100}%",
                    "path": paths["candidate"],
                    "candidate_path": paths["candidate"],
                    "baseline_path": paths["bicubic"],
                    "bicubic_path": paths["bicubic"],
                    "width": int(dimensions[0]),
                    "height": int(dimensions[1]),
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
            candidate_b64 = _encode_png_b64(Path(crop["candidate_path"]))
            bicubic_b64 = _encode_png_b64(Path(crop["bicubic_path"]))
            if not candidate_b64 or not bicubic_b64:
                continue
            region = html.escape(str(crop["region"]))
            zoom_label = html.escape(str(crop["zoom_label"]))
            crop_html.append(
                f"""
                <div class="crop-card">
                  <div class="crop-hdr">
                    <strong>{region}</strong>
                    <span>{html.escape(str(crop['kind']))} &bull; {zoom_label} ({crop['width']}x{crop['height']})</span>
                  </div>
                  <div class="crop-pair">
                    <div class="crop-img-wrap"><strong>Fidelis candidate</strong><img src="{candidate_b64}" alt="{region} {zoom_label} candidate"></div>
                    <div class="crop-img-wrap"><strong>4x bicubic reference</strong><img src="{bicubic_b64}" alt="{region} {zoom_label} bicubic"></div>
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
  .crop-pair {{ display: flex; gap: 8px; align-items: flex-start; }}
  .crop-img-wrap {{ flex: 1; min-width: 0; overflow: auto; padding: 8px; text-align: center; }}
  .crop-img-wrap img {{ max-width: 100%; height: auto; image-rendering: pixelated; }}
</style>
</head>
<body>
  <div class="header">
    <div>
      <h1>Fidelis Visual Audition &amp; Benchmark Report</h1>
      <div class="muted">Report Type: <strong>MODEL_VS_BICUBIC_AUDITION</strong> &bull; Independent images: candidate and 4x bicubic</div>
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
        case_id: str | None = None,
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

    outcome = _screened_audition_outcome(detail_metrics, result.drift_report)

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
    cases: Sequence[Mapping[str, Any]] | None = None,
    runner: RestorationRunner | None = None,
    *,
    output_dir: str | Path,
    blind_seed: int = 20261110,
    apply_texture_guard: bool = True,
    generate_html: bool = True,
    asset_root: str | Path | None = None,
    blind_split: str = "held_out",
    source_rgb: np.ndarray | None = None,
    candidate_4x_rgb: np.ndarray | None = None,
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
        outcome = _screened_audition_outcome(detail_metrics, result.drift_report)
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


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_safe_master_file(master_root: Path, filename: str) -> Path:
    if not isinstance(filename, str) or not filename.strip():
        raise ValueError("Off-repo manifest entry requires a non-empty filename")
    rel = Path(filename)
    if rel.is_absolute() or ".." in rel.parts:
        raise ValueError(f"Unsafe off-repo filename {filename!r}")
    root_resolved = master_root.resolve()
    candidate = root_resolved / rel
    if not candidate.parent.resolve().is_relative_to(root_resolved):
        raise ValueError(f"Off-repo filename escapes master root: {filename!r}")
    if candidate.exists() and not candidate.resolve().is_relative_to(root_resolved):
        raise ValueError(f"Off-repo symlink escapes master root: {filename!r}")
    return candidate


def _resolve_manifest_entry_source(
    raw_entry: Mapping[str, Any],
    *,
    case_id: str,
    asset_root: Path | None,
    master_root: Path | None,
) -> tuple[Path, str | None, bool]:
    """Return (resolved_path, expected_sha256, is_off_repo)."""
    if raw_entry.get("source_path"):
        src_p = Path(str(raw_entry["source_path"]))
        if asset_root is not None and not src_p.is_absolute():
            src_p = asset_root / src_p
        return src_p, raw_entry.get("source_sha256"), False

    source_obj = raw_entry.get("source")
    if isinstance(source_obj, Mapping):
        if source_obj.get("path"):
            src_p = Path(str(source_obj["path"]))
            if asset_root is not None and not src_p.is_absolute():
                src_p = asset_root / src_p
            return src_p, source_obj.get("sha256"), False
        if source_obj.get("storage") == "off_repo" or source_obj.get("filename"):
            if master_root is None:
                raise ValueError(
                    f"{case_id}: --master-root is required to resolve off-repo source"
                )
            filename = source_obj.get("filename")
            if not filename:
                raise ValueError(f"{case_id}: off-repo entry has no filename")
            return (
                _resolve_safe_master_file(master_root, str(filename)),
                source_obj.get("sha256"),
                True,
            )

    if raw_entry.get("filename"):
        if master_root is None:
            raise ValueError(
                f"{case_id}: --master-root is required to resolve off-repo asset"
            )
        return (
            _resolve_safe_master_file(master_root, str(raw_entry["filename"])),
            raw_entry.get("sha256"),
            True,
        )

    raise KeyError(f"Case {case_id!r} missing 'source_path', 'source', or 'filename'")


def _resolve_roi_kind_and_policy(
    roi: Mapping[str, Any], *, case_id: str, rid: str
) -> tuple[str, str]:
    raw_kind = roi.get("kind")
    if isinstance(raw_kind, str) and raw_kind in VALID_ROI_KINDS:
        kind = raw_kind
    else:
        raw_type = roi.get("roi_type")
        if isinstance(raw_type, str) and raw_type in VALID_ROI_KINDS:
            kind = raw_type
        elif isinstance(raw_type, str) and raw_type in _MANIFEST_ROI_TYPE_TO_KIND:
            kind = _MANIFEST_ROI_TYPE_TO_KIND[raw_type]
        else:
            raise ValueError(
                f"{case_id}: ROI {rid} has unsupported kind/roi_type {raw_type or raw_kind!r}"
            )

    raw_policy = roi.get("policy")
    if isinstance(raw_policy, str) and raw_policy in VALID_POLICIES:
        policy = raw_policy
    elif isinstance(roi.get("must_lock_base"), bool):
        policy = "preserve" if roi["must_lock_base"] else "texture_allowed"
    elif kind in ("hardware", "seam", "logo", "text", "identity", "alpha_boundary"):
        policy = "preserve"
    else:
        policy = "texture_allowed"
    return kind, policy


def _convert_bbox_norm_to_rect(
    bbox_norm: Any, *, case_id: str, rid: str, image_size: tuple[int, int]
) -> list[int]:
    if bbox_norm is None:
        raise ValueError(f"{case_id}: ROI {rid} has null bbox_norm")
    if (
        not isinstance(bbox_norm, (list, tuple))
        or len(bbox_norm) != 4
        or any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in bbox_norm)
    ):
        raise ValueError(f"{case_id}: ROI {rid} bbox_norm must be [x0, y0, x1, y1]")
    x0, y0, x1, y1 = [float(v) for v in bbox_norm]
    if not (0.0 <= x0 < x1 <= 1.0 and 0.0 <= y0 < y1 <= 1.0):
        raise ValueError(f"{case_id}: ROI {rid} bbox_norm out of [0,1] bounds: {bbox_norm!r}")

    w, h = image_size
    px = max(0, min(w - 1, round(x0 * w)))
    py = max(0, min(h - 1, round(y0 * h)))
    x2 = max(px + 1, min(w, round(x1 * w)))
    y2 = max(py + 1, min(h, round(y1 * h)))
    return [px, py, x2 - px, y2 - py]


def _convert_manifest_rois(
    raw_entry: Mapping[str, Any], *, case_id: str, image_path: Path
) -> list[dict[str, Any]]:
    raw_rois = raw_entry.get("rois")
    if raw_rois is None:
        raw_rois = raw_entry.get("critical_rois")
    if not raw_rois:
        return []
    if not isinstance(raw_rois, Sequence) or isinstance(raw_rois, (str, bytes)):
        raise ValueError(f"{case_id}: ROIs must be a sequence")

    needs_dims = any(
        isinstance(r, Mapping) and "rect" not in r and "bbox" not in r and "bbox_norm" in r
        for r in raw_rois
    )
    image_size: tuple[int, int] | None = None
    if needs_dims:
        with Image.open(image_path) as img:
            image_size = img.size

    converted: list[dict[str, Any]] = []
    for idx, roi in enumerate(raw_rois):
        if not isinstance(roi, Mapping):
            raise ValueError(f"{case_id}: ROI[{idx}] must be a mapping")
        rid = str(roi.get("id") or roi.get("roi_id") or f"roi_{idx}").strip() or f"roi_{idx}"
        kind, policy = _resolve_roi_kind_and_policy(roi, case_id=case_id, rid=rid)
        item: dict[str, Any] = {
            "id": rid,
            "kind": kind,
            "policy": policy,
            "override": roi.get("override"),
            "label": str(roi.get("label", rid)),
        }
        if "rect" in roi:
            item["rect"] = list(roi["rect"])
        elif "bbox" in roi:
            item["bbox"] = list(roi["bbox"])
        elif "bbox_norm" in roi:
            if image_size is None:
                raise RuntimeError(f"{case_id}: image dimensions unavailable for bbox_norm")
            item["rect"] = _convert_bbox_norm_to_rect(
                roi.get("bbox_norm"), case_id=case_id, rid=rid, image_size=image_size
            )
        else:
            raise ValueError(f"{case_id}: ROI {rid} missing rect, bbox, or bbox_norm")
        converted.append(item)
    return converted


def _extract_manifest_entries(
    manifest: Mapping[str, Any] | Sequence[Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    if isinstance(manifest, Mapping):
        if isinstance(manifest.get("cases"), list):
            return manifest["cases"]
        if isinstance(manifest.get("assets"), list):
            return manifest["assets"]
        raise ValueError("Manifest must contain a 'cases' or 'assets' list")
    if isinstance(manifest, Sequence) and not isinstance(manifest, (str, bytes)):
        return list(manifest)
    raise ValueError("Manifest must be a mapping or list of cases")


def _verify_expected_sha(src_path: Path, expected_sha: Any, *, case_id: str) -> str | None:
    if expected_sha is None:
        return None
    sha_norm = str(expected_sha).strip().lower()
    if not _SHA256_RE.fullmatch(sha_norm):
        raise ValueError(f"{case_id}: invalid expected sha256 {expected_sha!r}")
    actual_sha = _sha256_file(src_path)
    if actual_sha != sha_norm:
        raise ValueError(f"{case_id}: source SHA-256 mismatch ({actual_sha} != {sha_norm})")
    return sha_norm


def _normalize_manifest_entry(
    raw_entry: Mapping[str, Any],
    *,
    cid: str,
    entry_split: str,
    scale: int,
    asset_root: Path | None,
    master_root: Path | None,
    skip_missing: bool,
    exclude_synthetic: bool,
) -> tuple[dict[str, Any] | None, str | None]:
    """Validate and convert a single manifest entry, returning (case_dict, skip_reason)."""
    if exclude_synthetic and (
        raw_entry.get("synthetic") is True or raw_entry.get("ground_truth_eligible") is False
    ):
        return None, "synthetic_excluded"

    if raw_entry.get("availability") == "missing":
        if skip_missing:
            return None, "source_missing"
        raise FileNotFoundError(f"{cid}: manifest marks availability='missing'")

    rights_obj = raw_entry.get("rights")
    if isinstance(rights_obj, Mapping) and rights_obj.get("cleared") is False:
        if skip_missing:
            return None, "rights_uncleared"
        raise ValueError(f"{cid}: rights.cleared is False")

    try:
        src_path, expected_sha, is_off_repo = _resolve_manifest_entry_source(
            raw_entry, case_id=cid, asset_root=asset_root, master_root=master_root
        )
    except KeyError:
        if skip_missing:
            return None, "source_missing"
        raise

    if not src_path.is_file():
        if skip_missing:
            return None, "source_missing"
        raise FileNotFoundError(f"{cid}: source file missing: {src_path}")

    sha_norm = _verify_expected_sha(src_path, expected_sha, case_id=cid)

    try:
        rois = _convert_manifest_rois(raw_entry, case_id=cid, image_path=src_path)
    except ValueError as exc:
        if skip_missing and "null bbox_norm" in str(exc):
            return None, "roi_unannotated"
        raise

    case_dict: dict[str, Any] = {
        "id": cid,
        "source_path": str(src_path),
        "scale": int(raw_entry.get("scale", scale)),
        "roi_space": str(raw_entry.get("roi_space", "source")),
        "split": entry_split,
        "category": str(raw_entry.get("category", "model_apparel")),
        "rois": rois,
    }
    if raw_entry.get("target_dimensions") is not None:
        case_dict["target_dimensions"] = raw_entry["target_dimensions"]
    if is_off_repo and sha_norm is not None:
        case_dict["source_sha256"] = sha_norm
    return case_dict, None


def load_audition_cases_from_manifest(
    manifest: Mapping[str, Any] | Sequence[Mapping[str, Any]],
    *,
    scale: int = 4,
    asset_root: str | Path | None = None,
    master_root: str | Path | None = None,
    split: str | None = None,
    case_ids: Sequence[str] = (),
    skip_missing: bool = False,
    exclude_synthetic: bool = True,
    default_split: str = "calibration",
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Normalize audition, corpus_manifest, or melato_corpus_manifest entries into audition cases."""
    raw_entries = _extract_manifest_entries(manifest)
    a_root = Path(asset_root) if asset_root is not None else None
    m_root = Path(master_root) if master_root is not None else None
    wanted_ids = {str(cid).strip() for cid in case_ids if str(cid).strip()}
    split_filter = None if split in (None, "", "all") else str(split)

    cases: list[dict[str, Any]] = []
    reason_counts: dict[str, int] = {}
    skipped_count = 0
    seen_ids: set[str] = set()

    for raw_entry in raw_entries:
        if not isinstance(raw_entry, Mapping):
            raise ValueError("Manifest entry must be a JSON object")
        cid = str(
            raw_entry.get("id") or raw_entry.get("case_id") or raw_entry.get("asset_id") or ""
        ).strip()
        if not cid:
            raise KeyError("Manifest entry missing 'id', 'case_id', or 'asset_id'")
        seen_ids.add(cid)

        if wanted_ids and cid not in wanted_ids:
            continue
        entry_split = str(raw_entry.get("split") or default_split)
        if split_filter is not None and entry_split != split_filter:
            continue

        case_dict, skip_reason = _normalize_manifest_entry(
            raw_entry,
            cid=cid,
            entry_split=entry_split,
            scale=scale,
            asset_root=a_root,
            master_root=m_root,
            skip_missing=skip_missing,
            exclude_synthetic=exclude_synthetic,
        )
        if skip_reason is not None:
            skipped_count += 1
            reason_counts[skip_reason] = reason_counts.get(skip_reason, 0) + 1
        elif case_dict is not None:
            cases.append(case_dict)

    missing_requested = sorted(wanted_ids - seen_ids)
    if missing_requested:
        raise ValueError(f"Requested case IDs not found in manifest: {missing_requested}")
    if not cases:
        raise ValueError("No runnable audition cases matched manifest filters")

    return cases, {
        "total_entries": len(raw_entries),
        "selected_count": len(cases),
        "skipped_count": skipped_count,
        "skipped_reasons": reason_counts,
        "selected_ids": [c["id"] for c in cases],
    }
