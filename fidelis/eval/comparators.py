"""Reproducible comparator evaluation and blind pairwise scoring for Fidelis (`F12`).

Every comparator produces separate single-image full-resolution files and explicit
receipts (settings, elapsed time, cost, output SHA-256, and reference-labelled
metrics). Unavailable accounts, missing models, or disallowed remote transfers are
reported as unavailable/skipped rather than simulated or omitted from denominators.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import random
import time
from typing import Any, Callable, Optional

import cv2
import numpy as np
from PIL import Image

from fidelis.eval.corpus_manifest import (
    audit,
    digest,
    inspect_image,
    local_path,
    verify,
)
from fidelis.eval.pipeline_metrics import measure_pipeline_metrics

CANONICAL_COMPARATORS = (
    "interpolation",
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

    output_path: Optional[Path]
    status: str  # "completed" | "rejected_unsupported" | "failed" | "unavailable"
    settings: dict[str, Any]
    manual_adjustments: Optional[str] = None
    elapsed_seconds: Optional[float] = None
    cost_usd: Optional[float] = None
    error: Optional[str] = None


def interpolation_runner(
    case: dict[str, Any],
    source_path: Path,
    dest_path: Path,
) -> ComparatorOutput:
    """Built-in deterministic Lanczos interpolation baseline."""
    start = time.monotonic()
    if case.get("expected_behavior") == "reject_unsupported_input":
        return ComparatorOutput(
            output_path=None,
            status="rejected_unsupported",
            settings={"method": "lanczos3", "target_dimensions": case["target_dimensions"]},
            elapsed_seconds=round(time.monotonic() - start, 6),
            cost_usd=0.0,
            error="Rejected negative edge case per expected_behavior",
        )
    if not isinstance(target := case.get("target_dimensions"), list) or len(target) != 2 or any(type(v) is not int or v <= 0 for v in target):
        return ComparatorOutput(
            output_path=None,
            status="unavailable",
            settings={"method": "lanczos3"},
            elapsed_seconds=round(time.monotonic() - start, 6),
            cost_usd=0.0,
            error="target_dimensions missing or invalid",
        )
    tw, th = target
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = dest_path.with_suffix(".tmp.png")
    with Image.open(source_path) as image:
        rgb = image.convert("RGB")
        resized = rgb.resize((tw, th), Image.Resampling.LANCZOS)
        resized.save(tmp_path, format="PNG")
    os.replace(tmp_path, dest_path)
    return ComparatorOutput(
        output_path=dest_path,
        status="completed",
        settings={"method": "lanczos3", "target_dimensions": [tw, th]},
        manual_adjustments=None,
        elapsed_seconds=round(time.monotonic() - start, 6),
        cost_usd=0.0,
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
        )

    _run.__name__ = f"imported_{comparator_name}"
    return _run


def _evaluate_output_record(
    case: dict[str, Any],
    comparator: str,
    source_path: Path,
    result: ComparatorOutput,
    *,
    ground_truth_path: Optional[Path] = None,
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
    }
    if result.status != "completed" or result.output_path is None:
        return base

    out_path = Path(result.output_path)
    if not out_path.is_file():
        return {**base, "status": "failed", "error": f"Comparator output missing: {out_path}"}

    target = case.get("target_dimensions")
    if not isinstance(target, list) or len(target) != 2 or any(type(v) is not int or v <= 0 for v in target):
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
    return {
        **base,
        "output_path": str(out_path),
        "output_sha256": info["sha256"],
        "output_dimensions": info["dimensions"],
        "metrics": metrics,
        "metric_context": context,
    }


def run_comparators(
    corpus_record_or_manifest: dict[str, Any],
    *,
    asset_root: str | Path,
    output_dir: str | Path,
    runners: Optional[dict[str, Callable[[dict[str, Any], Path, Path], ComparatorOutput]]] = None,
    protocol: Optional[dict[str, Any]] = None,
    slots: Optional[dict[str, Any]] = None,
    allow_regression_manifest: bool = False,
) -> dict[str, Any]:
    """Execute configured comparators on verified corpus lock or explicit regression manifest."""
    root = Path(asset_root).resolve()
    out_root = Path(output_dir)
    out_root.mkdir(parents=True, exist_ok=True)

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

    slot_by_id = {row["id"]: row for row in slot_doc["slots"]}
    comparators = tuple(prot.get("comparators", CANONICAL_COMPARATORS))
    active_runners: dict[str, Callable[[dict[str, Any], Path, Path], ComparatorOutput]] = {
        "interpolation": interpolation_runner,
        **(runners or {}),
    }

    case_results: list[dict[str, Any]] = []
    audit_by_id = {row["id"]: row for row in audit_report["cases"]}

    for case in manifest["cases"]:
        cid = case["id"]
        audit_row = audit_by_id[cid]
        if not audit_row["available"]:
            continue
        if corpus_mode == "frozen_production_lock" and case["role"] != "production":
            continue

        split = slot_by_id[case["slot_id"]]["split"] if case.get("slot_id") in slot_by_id else "regression"
        src_path = local_path(root, case["source"]["path"])
        remote_allowed = case.get("rights", {}).get("remote_processing") == "allowed"
        gt_rel = case.get("ground_truth_path")
        gt_path = local_path(root, gt_rel) if gt_rel else None

        outputs: dict[str, dict[str, Any]] = {}
        for comp in comparators:
            dest_png = out_root / split / cid / f"{comp}.png"
            if comp in REMOTE_COMPARATORS and not remote_allowed:
                outputs[comp] = _evaluate_output_record(
                    case,
                    comp,
                    src_path,
                    ComparatorOutput(
                        output_path=None,
                        status="skipped_remote_disallowed",
                        settings={},
                        error="rights.remote_processing != 'allowed'; remote comparator execution blocked",
                    ),
                )
                continue
            runner = active_runners.get(comp)
            if runner is None:
                outputs[comp] = _evaluate_output_record(
                    case,
                    comp,
                    src_path,
                    ComparatorOutput(
                        output_path=None,
                        status="unavailable",
                        settings={},
                        error=f"No local/account comparator configured for {comp!r}",
                    ),
                )
                continue
            t0 = time.monotonic()
            try:
                res = runner(case, src_path, dest_png)
                if res.elapsed_seconds is None and res.status == "completed":
                    res = ComparatorOutput(**{**asdict(res), "elapsed_seconds": round(time.monotonic() - t0, 6)})
            except Exception as exc:
                res = ComparatorOutput(
                    output_path=None,
                    status="failed",
                    settings={},
                    elapsed_seconds=round(time.monotonic() - t0, 6),
                    error=f"{type(exc).__name__}: {exc}",
                )
            outputs[comp] = _evaluate_output_record(
                case, comp, src_path, res, ground_truth_path=gt_path
            )

        case_results.append(
            {
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
        )

    summary_by_comparator: dict[str, dict[str, Any]] = {}
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

    report = {
        "schema_version": 1,
        "corpus_mode": corpus_mode,
        "lock_sha256": lock_sha,
        "protocol_id": prot.get("id"),
        "output_policy": prot.get("output_policy"),
        "single_image_per_file": True,
        "case_count": len(case_results),
        "comparators": summary_by_comparator,
        "cases": case_results,
    }
    report["report_sha256"] = digest({k: v for k, v in report.items() if k != "report_sha256"})
    return report


def build_blind_pairwise_manifest(
    comparison_report: dict[str, Any],
    candidate_a: str,
    candidate_b: str,
    *,
    split: str = "held_out",
    seed: int = 20261110,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build blind randomized A/B comparison ballot keeping separate native PNG paths."""
    if candidate_a == candidate_b:
        raise ValueError("Pairwise comparison requires two distinct comparators")
    rng = random.Random(seed)
    eligible_cases = [
        case
        for case in comparison_report.get("cases", [])
        if case.get("split") == split
        and case["outputs"].get(candidate_a, {}).get("status") == "completed"
        and case["outputs"].get(candidate_b, {}).get("status") == "completed"
    ]
    shuffled = list(eligible_cases)
    rng.shuffle(shuffled)

    ballot_items = []
    answer_key = {}
    for idx, case in enumerate(shuffled, start=1):
        pair_id = f"pair_{idx:03d}"
        swap = bool(rng.randint(0, 1))
        left_comp, right_comp = (candidate_b, candidate_a) if swap else (candidate_a, candidate_b)
        ballot_items.append(
            {
                "pair_id": pair_id,
                "category": case["category"],
                "source_path": case["source_path"],
                "option_left": case["outputs"][left_comp]["output_path"],
                "option_right": case["outputs"][right_comp]["output_path"],
                "choice": None,  # "left" | "right" | "tie"
                "critical_defect_left": False,
                "critical_defect_right": False,
                "notes": "",
            }
        )
        answer_key[pair_id] = {
            "case_id": case["case_id"],
            "category": case["category"],
            "left": left_comp,
            "right": right_comp,
        }

    ballot = {
        "schema_version": 1,
        "split": split,
        "seed": seed,
        "pair_count": len(ballot_items),
        "single_image_per_file": True,
        "items": ballot_items,
    }
    key_doc = {
        "schema_version": 1,
        "candidate_a": candidate_a,
        "candidate_b": candidate_b,
        "split": split,
        "seed": seed,
        "mapping": answer_key,
    }
    return ballot, key_doc


def _bootstrap_ci(values: np.ndarray, *, n_resamples: int = 1000, seed: int = 2026) -> list[float]:
    if len(values) == 0:
        return [0.0, 0.0]
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(values), size=(n_resamples, len(values)))
    means = values[idx].mean(axis=1)
    lo, hi = np.percentile(means, [2.5, 97.5])
    return [round(float(lo), 4), round(float(hi), 4)]


def summarize_blind_reviews(
    completed_ballot: dict[str, Any],
    answer_key: dict[str, Any],
    *,
    subject_comparator: str,
    target_comparator: str,
    n_bootstrap: int = 1000,
) -> dict[str, Any]:
    """Score blind pairwise ballot with bootstrap CIs and proposed QUALITY_GATES thresholds."""
    mapping = answer_key.get("mapping", {})
    pref_ties: list[float] = []
    wins: list[float] = []
    by_category: dict[str, list[float]] = {}
    critical_defects_subject = 0
    unreviewed = 0

    for entry in completed_ballot.get("items", []):
        pid = entry.get("pair_id")
        meta = mapping.get(pid)
        if not meta:
            raise ValueError(f"Ballot entry {pid!r} missing from blind answer key")
        pair_set = {meta["left"], meta["right"]}
        if pair_set != {subject_comparator, target_comparator}:
            continue
        choice = entry.get("choice")
        if choice is None:
            unreviewed += 1
            continue
        if choice not in ("left", "right", "tie"):
            raise ValueError(f"Invalid blind ballot choice {choice!r} on {pid}")

        subject_side = "left" if meta["left"] == subject_comparator else "right"
        if (subject_side == "left" and entry.get("critical_defect_left")) or (
            subject_side == "right" and entry.get("critical_defect_right")
        ):
            critical_defects_subject += 1

        is_win = 1.0 if choice == subject_side else 0.0
        is_pref_or_tie = 1.0 if choice in (subject_side, "tie") else 0.0
        wins.append(is_win)
        pref_ties.append(is_pref_or_tie)
        by_category.setdefault(meta["category"], []).append(is_pref_or_tie)

    n = len(wins)
    if n == 0 or unreviewed > 0:
        return {
            "schema_version": 1,
            "subject": subject_comparator,
            "target": target_comparator,
            "sample_count": n,
            "unreviewed_count": unreviewed,
            "status": "incomplete" if unreviewed > 0 else "unavailable",
            "preliminary_small_sample": True,
            "meets_proposed_thresholds": False,
        }

    wins_arr = np.asarray(wins, dtype=np.float64)
    pref_arr = np.asarray(pref_ties, dtype=np.float64)
    win_rate = round(float(wins_arr.mean()), 4)
    pref_tie_rate = round(float(pref_arr.mean()), 4)
    cat_rates = {
        cat: {
            "n": len(vals),
            "preference_plus_tie_rate": round(float(np.mean(vals)), 4),
        }
        for cat, vals in sorted(by_category.items())
    }
    min_cat_rate = min(v["preference_plus_tie_rate"] for v in cat_rates.values())
    meets = (
        pref_tie_rate >= 0.80
        and win_rate >= 0.50
        and min_cat_rate >= 0.60
        and critical_defects_subject == 0
    )
    return {
        "schema_version": 1,
        "subject": subject_comparator,
        "target": target_comparator,
        "sample_count": n,
        "unreviewed_count": 0,
        "preliminary_small_sample": n < 100,
        "win_rate": win_rate,
        "win_rate_ci95": _bootstrap_ci(wins_arr, n_resamples=n_bootstrap),
        "preference_plus_tie_rate": pref_tie_rate,
        "preference_plus_tie_ci95": _bootstrap_ci(pref_arr, n_resamples=n_bootstrap),
        "min_category_preference_plus_tie_rate": min_cat_rate,
        "by_category": cat_rates,
        "critical_defects_subject": critical_defects_subject,
        "meets_proposed_thresholds": bool(meets),
        "status": "preliminary_passed" if meets and n < 100 else ("passed" if meets else "failed"),
    }
