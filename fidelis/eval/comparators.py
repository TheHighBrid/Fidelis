"""Reproducible comparator evaluation and blind pairwise scoring for Fidelis (`F12`).

Every comparator produces separate single-image full-resolution files and explicit
receipts (settings, elapsed time, cost, output SHA-256, and reference-labelled
metrics). Unavailable accounts, missing models, or disallowed remote transfers are
reported as unavailable/skipped rather than simulated or omitted from denominators.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image

from fidelis.eval.blind_review import (  # noqa: F401  # Public compatibility exports
    build_blind_pairwise_manifest as build_blind_pairwise_manifest,
)
from fidelis.eval.blind_review import (  # noqa: F401
    summarize_blind_reviews as summarize_blind_reviews,
)
from fidelis.eval.corpus_manifest import (
    audit,
    digest,
    inspect_image,
    local_path,
    verify,
)
from fidelis.eval.pipeline_metrics import (
    measure_pipeline_metrics,
    measure_scale_matched_metrics,
)

CANONICAL_COMPARATORS = (
    "interpolation",
    "bicubic",
    "selected_deterministic_base",
    "fidelis",
    "vosr_challenger",
    "pinned_clarity",
    "dated_krea",
)
REMOTE_COMPARATORS = frozenset({"pinned_clarity", "dated_krea"})


@dataclass(frozen=True)
class ComparatorOutput:
    """Result returned by a callable comparator runner for a single case."""

    output_path: Path | None
    status: str  # "completed" | "rejected_unsupported" | "failed" | "unavailable"
    settings: dict[str, Any]
    manual_adjustments: str | None = None
    elapsed_seconds: float | None = None
    cost_usd: float | None = None
    error: str | None = None
    is_imported: bool = False


def _deterministic_resample_runner(
    case: dict[str, Any],
    source_path: Path,
    dest_path: Path,
    *,
    method_name: str,
    resampling: Image.Resampling,
) -> ComparatorOutput:
    """Shared deterministic PIL resampling baseline."""
    start = time.monotonic()
    if case.get("expected_behavior") == "reject_unsupported_input":
        return ComparatorOutput(
            output_path=None,
            status="rejected_unsupported",
            settings={"method": method_name, "target_dimensions": case.get("target_dimensions")},
            elapsed_seconds=round(time.monotonic() - start, 6),
            cost_usd=0.0,
            error="Rejected negative edge case per expected_behavior",
        )
    if not isinstance(target := case.get("target_dimensions"), list) or len(target) != 2 or any(not isinstance(v, int) or isinstance(v, bool) or v <= 0 for v in target):
        return ComparatorOutput(
            output_path=None,
            status="unavailable",
            settings={"method": method_name},
            elapsed_seconds=round(time.monotonic() - start, 6),
            cost_usd=0.0,
            error="target_dimensions missing or invalid",
        )
    tw, th = target
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = dest_path.with_suffix(".tmp.png")
    try:
        with Image.open(source_path) as image:
            rgb = image.convert("RGB")
            resized = rgb.resize((tw, th), resampling)
            resized.save(tmp_path, format="PNG")
        os.replace(tmp_path, dest_path)
    except (FileNotFoundError, OSError) as exc:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        return ComparatorOutput(
            output_path=None,
            status="failed",
            settings={"method": method_name, "target_dimensions": [tw, th]},
            elapsed_seconds=round(time.monotonic() - start, 6),
            cost_usd=0.0,
            error=f"Failed to process source image {source_path}: {exc}",
        )
    return ComparatorOutput(
        output_path=dest_path,
        status="completed",
        settings={"method": method_name, "target_dimensions": [tw, th]},
        manual_adjustments=None,
        elapsed_seconds=round(time.monotonic() - start, 6),
        cost_usd=0.0,
    )


def interpolation_runner(
    case: dict[str, Any],
    source_path: Path,
    dest_path: Path,
) -> ComparatorOutput:
    """Built-in deterministic Lanczos interpolation baseline."""
    return _deterministic_resample_runner(
        case,
        source_path,
        dest_path,
        method_name="lanczos3",
        resampling=Image.Resampling.LANCZOS,
    )


def bicubic_runner(
    case: dict[str, Any],
    source_path: Path,
    dest_path: Path,
) -> ComparatorOutput:
    """Built-in deterministic 4x Bicubic interpolation baseline."""
    return _deterministic_resample_runner(
        case,
        source_path,
        dest_path,
        method_name="bicubic",
        resampling=Image.Resampling.BICUBIC,
    )


def make_imported_output_runner(
    comparator_name: str,
    imported_dir: Path,
) -> Callable[[dict[str, Any], Path, Path], ComparatorOutput]:
    """Read pre-exported comparator results + optional `<case_id>.meta.json` disclosures."""
    imported_dir = Path(imported_dir)

    def _run(case: dict[str, Any], _source_path: Path, dest_path: Path) -> ComparatorOutput:
        case_id = case["id"]
        src_candidate = None
        for ext in (".png", ".tif", ".tiff", ".webp", ".jpg"):
            probe = imported_dir / f"{case_id}{ext}"
            if probe.is_file():
                src_candidate = probe
                break
        meta_path = imported_dir / f"{case_id}.meta.json"
        meta: dict[str, Any] = {}
        if meta_path.is_file():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))

        if src_candidate is None:
            return ComparatorOutput(
                output_path=None,
                status=meta.get("status", "unavailable"),
                settings=meta.get("settings", {}),
                manual_adjustments=meta.get("manual_adjustments"),
                elapsed_seconds=meta.get("elapsed_seconds"),
                cost_usd=meta.get("cost_usd"),
                error=meta.get("error", f"No output file found for {case_id} in {imported_dir}"),
                is_imported=True,
            )

        dest_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = dest_path.with_suffix(".tmp.png")
        with Image.open(src_candidate) as im:
            im.load()
            if im.mode in ("RGB", "RGBA"):
                im.save(tmp_path, format="PNG")
            else:
                im.convert("RGB").save(tmp_path, format="PNG")
        os.replace(tmp_path, dest_path)
        return ComparatorOutput(
            output_path=dest_path,
            status="completed",
            settings=meta.get("settings", {"imported_from": src_candidate.name}),
            manual_adjustments=meta.get("manual_adjustments"),
            elapsed_seconds=meta.get("elapsed_seconds"),
            cost_usd=meta.get("cost_usd"),
            is_imported=True,
        )

    _run.__name__ = f"imported_{comparator_name}"
    return _run


def _evaluate_output_record(
    case: dict[str, Any],
    comparator: str,
    source_path: Path,
    result: ComparatorOutput,
    *,
    ground_truth_path: Path | None = None,
    bicubic_bgr: np.ndarray | None = None,
    rois: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    base = {
        "comparator": comparator,
        "status": result.status,
        "settings": result.settings,
        "manual_adjustments": result.manual_adjustments,
        "elapsed_seconds": result.elapsed_seconds,
        "cost_usd": result.cost_usd,
        "error": result.error,
        "output_path": None,
        "output_sha256": None,
        "output_dimensions": None,
        "metrics": None,
        "metric_context": None,
        "scale_matched_metrics": None,
    }
    if result.status != "completed" or result.output_path is None:
        return base

    return _evaluate_completed_output(base, case, source_path, result.output_path, ground_truth_path, bicubic_bgr, rois)


def _valid_target(target):
    return isinstance(target, list) and len(target) == 2 and all(
        isinstance(v, int) and not isinstance(v, bool) and v > 0 for v in target
    )


def _evaluate_completed_output(base, case, source_path, output_path, ground_truth_path, bicubic_bgr, rois):
    out_path = Path(output_path)
    if not out_path.is_file():
        return {**base, "status": "failed", "error": f"Comparator output missing: {out_path}"}

    target = case.get("target_dimensions")
    if not _valid_target(target):
        return {
            **base,
            "status": "unavailable",
            "error": "target_dimensions missing or invalid",
        }
    info = inspect_image(out_path)
    tw, th = target
    if info["dimensions"] != [tw, th]:
        return {
            **base,
            "status": "failed",
            "output_path": str(out_path),
            "output_sha256": info["sha256"],
            "output_dimensions": info["dimensions"],
            "error": (
                f"Output dimensions {info['dimensions']} do not match target {[tw, th]}; "
                "silent resizing is forbidden"
            ),
        }

    metrics, context, scale_matched = _measure_output(case, source_path, out_path, ground_truth_path, bicubic_bgr, rois)
    return {
        **base,
        "output_path": str(out_path),
        "output_sha256": info["sha256"],
        "output_dimensions": info["dimensions"],
        "metrics": metrics,
        "metric_context": context,
        "scale_matched_metrics": scale_matched,
    }


def _measure_output(case, source_path, out_path, ground_truth_path, bicubic_bgr, rois):
    src_bgr = cv2.imread(str(source_path), cv2.IMREAD_COLOR)
    out_bgr = cv2.imread(str(out_path), cv2.IMREAD_COLOR)
    gt_bgr = (
        cv2.imread(str(ground_truth_path), cv2.IMREAD_COLOR)
        if ground_truth_path and ground_truth_path.is_file()
        else None
    )
    metrics, context = measure_pipeline_metrics(
        src_bgr,
        out_bgr,
        ground_truth_bgr=gt_bgr,
        ground_truth_requested=ground_truth_path is not None,
    )
    if ground_truth_path is not None and isinstance(case.get("ground_truth"), dict):
        context["ground_truth_sha256"] = case["ground_truth"].get("sha256")
    scale_matched = (
        measure_scale_matched_metrics(out_bgr, bicubic_bgr, src_bgr, rois=rois)
        if bicubic_bgr is not None
        else None
    )
    return metrics, context, scale_matched


def _load_verified_corpus(corpus_record_or_manifest, root, protocol, slots, allow_regression_manifest):
    if corpus_record_or_manifest.get("record_type") == "unsigned_corpus_lock":
        audit_report = verify(corpus_record_or_manifest, root)
        manifest = corpus_record_or_manifest["manifest"]
        prot = corpus_record_or_manifest["protocol"]
        slot_doc = corpus_record_or_manifest["slots"]
        corpus_mode = "frozen_production_lock"
        lock_sha = corpus_record_or_manifest["lock_sha256"]
    else:
        if not allow_regression_manifest:
            raise ValueError(
                "Refusing non-frozen manifest without allow_regression_manifest=True"
            )
        if protocol is None or slots is None:
            raise ValueError("Regression manifest evaluation requires protocol and slots")
        audit_report = audit(corpus_record_or_manifest, protocol, slots, root)
        manifest = corpus_record_or_manifest
        prot = protocol
        slot_doc = slots
        corpus_mode = "regression_only_unfrozen"
        lock_sha = None

    return audit_report, manifest, prot, slot_doc, corpus_mode, lock_sha


def _bicubic_reference(case, src_path):
    target_dims = case.get("target_dimensions")
    if not _valid_target(target_dims) or not src_path.is_file() or case.get("expected_behavior") == "reject_unsupported_input":
        return None
    with Image.open(src_path) as src_im:
        bic_rgb = np.asarray(src_im.convert("RGB").resize(tuple(target_dims), Image.Resampling.BICUBIC))
    return cv2.cvtColor(bic_rgb, cv2.COLOR_RGB2BGR)


def _execute_comparator(case, comp, src_path, dest_png, runner):
    if comp in REMOTE_COMPARATORS and case.get("rights", {}).get("remote_processing") != "allowed":
        return ComparatorOutput(None, "skipped_remote_disallowed", {}, error="rights.remote_processing != 'allowed'; remote comparator execution blocked")
    if runner is None:
        return ComparatorOutput(None, "unavailable", {}, error=f"No local/account comparator configured for {comp!r}")
    t0 = time.monotonic()
    try:
        res = runner(case, src_path, dest_png)
        if res.elapsed_seconds is None and res.status == "completed" and not res.is_imported:
            res = ComparatorOutput(**{**asdict(res), "elapsed_seconds": round(time.monotonic() - t0, 6)})
        return res
    except Exception as exc:  # noqa: BLE001
        return ComparatorOutput(None, "failed", {}, elapsed_seconds=round(time.monotonic() - t0, 6), error=f"{type(exc).__name__}: {exc}")


def _run_case(case, audit_row, split, root, out_root, comparators, active_runners):
    cid = case["id"]
    src_path = local_path(root, case["source"]["path"])
    gt_rel = case.get("ground_truth_path")
    gt_path = local_path(root, gt_rel) if gt_rel else None
    bicubic_bgr = _bicubic_reference(case, src_path)
    outputs = {}
    for comp in comparators:
        result = _execute_comparator(case, comp, src_path, out_root / split / cid / f"{comp}.png", active_runners.get(comp))
        outputs[comp] = _evaluate_output_record(case, comp, src_path, result, ground_truth_path=gt_path,
                                                bicubic_bgr=bicubic_bgr, rois=case.get("rois"))
    return {
        "case_id": cid,
        "role": case["role"],
        "slot_id": case.get("slot_id"),
        "split": split,
        "category": case["category"],
        "source_path": case["source"]["path"],
        "source_sha256": audit_row["observed"]["sha256"],
        "target_dimensions": case["target_dimensions"],
        "remote_processing": case.get("rights", {}).get("remote_processing"),
        "outputs": outputs,
    }


def _summarize_comparators(case_results, comparators):
    summary_by_comparator = {}
    for comp in comparators:
        statuses = [row["outputs"][comp]["status"] for row in case_results]
        costs = [
            float(row["outputs"][comp]["cost_usd"])
            for row in case_results
            if row["outputs"][comp]["cost_usd"] is not None
        ]
        times = [
            float(row["outputs"][comp]["elapsed_seconds"])
            for row in case_results
            if row["outputs"][comp]["elapsed_seconds"] is not None
        ]
        summary_by_comparator[comp] = {
            "total_cases": len(case_results),
            "completed": statuses.count("completed"),
            "failed": statuses.count("failed"),
            "rejected_unsupported": statuses.count("rejected_unsupported"),
            "skipped_remote_disallowed": statuses.count("skipped_remote_disallowed"),
            "unavailable": statuses.count("unavailable"),
            "total_cost_usd": round(sum(costs), 6) if costs else None,
            "mean_elapsed_seconds": round(sum(times) / len(times), 6) if times else None,
        }

    return summary_by_comparator


def run_comparators(
    corpus_record_or_manifest: dict[str, Any],
    *,
    asset_root: str | Path,
    output_dir: str | Path,
    runners: dict[str, Callable[[dict[str, Any], Path, Path], ComparatorOutput]] | None = None,
    protocol: dict[str, Any] | None = None,
    slots: dict[str, Any] | None = None,
    allow_regression_manifest: bool = False,
) -> dict[str, Any]:
    """Execute configured comparators on verified corpus lock or explicit regression manifest."""
    root, out_root = Path(asset_root).resolve(), Path(output_dir)
    out_root.mkdir(parents=True, exist_ok=True)
    audit_report, manifest, prot, slot_doc, corpus_mode, lock_sha = _load_verified_corpus(
        corpus_record_or_manifest, root, protocol, slots, allow_regression_manifest)
    slot_by_id = {row["id"]: row for row in slot_doc["slots"]}
    comparators = tuple(prot.get("comparators", CANONICAL_COMPARATORS))
    active_runners = {"interpolation": interpolation_runner, "bicubic": bicubic_runner, **(runners or {})}
    audit_by_id = {row["id"]: row for row in audit_report["cases"]}
    case_results = []
    for case in manifest["cases"]:
        audit_row = audit_by_id[case["id"]]
        if not audit_row["available"] or (corpus_mode == "frozen_production_lock" and case["role"] != "production"):
            continue
        split = slot_by_id[case["slot_id"]]["split"] if case.get("slot_id") in slot_by_id else "regression"
        case_results.append(_run_case(case, audit_row, split, root, out_root, comparators, active_runners))
    report = {
        "schema_version": 1,
        "corpus_mode": corpus_mode,
        "lock_sha256": lock_sha,
        "protocol_id": prot.get("id"),
        "output_policy": prot.get("output_policy"),
        "single_image_per_file": True,
        "case_count": len(case_results),
        "comparators": _summarize_comparators(case_results, comparators),
        "cases": case_results,
    }
    report["report_sha256"] = digest({k: v for k, v in report.items() if k != "report_sha256"})
    return report
