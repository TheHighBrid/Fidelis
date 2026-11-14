"""Held-out quality acceptance protocol and reproducibility receipt evaluator (F13 / MEL-66).

Enforces the gate order and proposed acceptance protocol in `docs/project/QUALITY_GATES.md`:
1. Corpus lock & split isolation: tuning/calibration occurs only on `calibration` slots;
   `held_out` slots (30 required across 5 categories, 6 per category) are evaluated once
   with a frozen calibration recipe.
2. Zero critical fidelity defects: any confirmed identity, logo/text, seam/zipper,
   hardware, or product-feature mutation fails acceptance immediately.
3. Blind pairwise preference thresholds:
   - Per comparator target: `preference_plus_ties_rate >= 0.80` and `win_rate >= 0.50`
   - Per category (across all 5 categories): `preference_plus_ties_rate >= 0.60`
   - Confidence intervals: exact Wilson score 95% CIs (`[low, high]`) and deterministic
     bootstrap CIs reported alongside sample sizes.
4. Reproducibility receipt & owner signoff: automated acceptance never fabricates
   human blind ballots or owner creative judgment. When `owner_creative_signoff` is not
   explicitly `approved`, `overall_status` is capped at `awaiting_owner_signoff`
   (if all quantitative gates pass) or `failed` / `blocked_incomplete_evidence`.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = "fidelis.quality_acceptance.v1"

REQUIRED_CATEGORIES: tuple[str, ...] = (
    "portrait",
    "model_apparel",
    "textile",
    "macro",
    "packshot_edge",
)

CRITICAL_DEFECT_TYPES: frozenset[str] = frozenset(
    {
        "identity_drift",
        "text_logo_corruption",
        "seam_zipper_hardware_mutation",
        "garment_construction_mutation",
        "product_geometry_mutation",
        "protected_pixel_violation",
        "internal_registration_drift",
        "plastic_skin_or_beauty_smoothing",
        "background_hallucination",
    }
)

REQUIRED_RECEIPT_FIELDS: tuple[str, ...] = (
    "code_sha",
    "corpus_lock_sha256",
    "calibration_recipe_sha256",
    "runtime_versions",
    "model_weight_hashes",
    "seed_policy",
    "colour_path",
)


@dataclass(frozen=True)
class AcceptanceThresholds:
    target_preference_plus_ties_min: float = 0.80
    target_win_rate_min: float = 0.50
    category_preference_plus_ties_min: float = 0.60
    min_held_out_cases_per_category: int = 6
    max_critical_defects: int = 0
    bootstrap_resamples: int = 1000
    bootstrap_seed: int = 20261110


def wilson_95_ci(successes: int, total: int) -> tuple[float, float]:
    """Compute the 95% Wilson score confidence interval for a binomial proportion."""
    if total <= 0:
        return (0.0, 0.0)
    z = 1.959963984540054
    phat = successes / total
    denom = 1.0 + (z * z) / total
    center = (phat + (z * z) / (2.0 * total)) / denom
    half = (
        z
        * math.sqrt((phat * (1.0 - phat) + (z * z) / (4.0 * total)) / total)
        / denom
    )
    return (
        round(max(0.0, center - half), 4),
        round(min(1.0, center + half), 4),
    )


def bootstrap_95_ci(
    outcomes: Sequence[int],
    *,
    resamples: int = 1000,
    seed: int = 20261110,
) -> tuple[float, float]:
    """Deterministic percentile bootstrap 95% CI for binary outcomes (0 or 1)."""
    n = len(outcomes)
    if n == 0:
        return (0.0, 0.0)
    if resamples <= 0:
        rate = round(sum(outcomes) / n, 4)
        return (rate, rate)
    rng = random.Random(seed)
    means: list[float] = []
    for _ in range(resamples):
        sample_sum = sum(outcomes[rng.randrange(n)] for _ in range(n))
        means.append(sample_sum / n)
    means.sort()
    lo_idx = max(0, int(math.floor(0.025 * (resamples - 1))))
    hi_idx = min(resamples - 1, int(math.ceil(0.975 * (resamples - 1))))
    return (round(means[lo_idx], 4), round(means[hi_idx], 4))


def validate_reproducibility_receipt(receipt: Mapping[str, Any] | None) -> dict[str, Any]:
    """Validate that a quality acceptance run carries a complete reproducibility receipt."""
    if not isinstance(receipt, Mapping):
        return {
            "complete": False,
            "missing_fields": list(REQUIRED_RECEIPT_FIELDS),
            "warnings": ["reproducibility_receipt is missing or not an object"],
        }
    missing: list[str] = []
    for key in REQUIRED_RECEIPT_FIELDS:
        val = receipt.get(key)
        if val is None or val == "" or val == {} or val == []:
            missing.append(key)

    warnings: list[str] = []
    provenance = str(receipt.get("provenance_status", "unsigned_execution_record"))
    if provenance == "c2pa_verified" and not receipt.get("c2pa_signature_verified"):
        warnings.append("provenance_status claims c2pa_verified without c2pa_signature_verified=True")

    return {
        "complete": len(missing) == 0 and len(warnings) == 0,
        "missing_fields": missing,
        "warnings": warnings,
        "code_sha": receipt.get("code_sha"),
        "corpus_lock_sha256": receipt.get("corpus_lock_sha256"),
        "calibration_recipe_sha256": receipt.get("calibration_recipe_sha256"),
    }


def _summarize_ballots(
    ballots: Sequence[Mapping[str, Any]],
    *,
    thresholds: AcceptanceThresholds,
    seed_offset: int = 0,
) -> dict[str, Any]:
    total = len(ballots)
    wins = sum(1 for b in ballots if b.get("outcome") == "fidelis_win")
    ties = sum(1 for b in ballots if b.get("outcome") == "tie")
    losses = sum(1 for b in ballots if b.get("outcome") == "comparator_win")

    win_rate = round(wins / total, 4) if total > 0 else None
    pref_or_tie = wins + ties
    pref_or_tie_rate = round(pref_or_tie / total, 4) if total > 0 else None

    win_outcomes = [1 if b.get("outcome") == "fidelis_win" else 0 for b in ballots]
    pref_outcomes = [
        1 if b.get("outcome") in ("fidelis_win", "tie") else 0 for b in ballots
    ]

    return {
        "sample_size": total,
        "fidelis_wins": wins,
        "ties": ties,
        "comparator_wins": losses,
        "win_rate": win_rate,
        "win_rate_wilson_95_ci": list(wilson_95_ci(wins, total)),
        "win_rate_bootstrap_95_ci": list(
            bootstrap_95_ci(
                win_outcomes,
                resamples=thresholds.bootstrap_resamples,
                seed=thresholds.bootstrap_seed + seed_offset,
            )
        ),
        "preference_plus_ties_rate": pref_or_tie_rate,
        "preference_plus_ties_wilson_95_ci": list(wilson_95_ci(pref_or_tie, total)),
        "preference_plus_ties_bootstrap_95_ci": list(
            bootstrap_95_ci(
                pref_outcomes,
                resamples=thresholds.bootstrap_resamples,
                seed=thresholds.bootstrap_seed + 100 + seed_offset,
            )
        ),
    }


def evaluate_held_out_acceptance(
    submission: Mapping[str, Any],
    *,
    thresholds: AcceptanceThresholds = AcceptanceThresholds(),
) -> dict[str, Any]:
    """Evaluate a calibration + blind held-out quality submission against F13 gates."""
    receipt_check = validate_reproducibility_receipt(
        submission.get("reproducibility_receipt")
    )

    calibration = submission.get("calibration_summary") or {}
    calibration_frozen = bool(calibration.get("recipe_frozen", False))
    calibration_cases = [
        str(cid) for cid in (calibration.get("case_ids") or []) if cid
    ]

    raw_ballots = submission.get("held_out_ballots")
    if not isinstance(raw_ballots, Sequence):
        raw_ballots = []

    valid_ballots: list[dict[str, Any]] = []
    split_contamination_ids: list[str] = []
    invalid_ballot_errors: list[str] = []
    critical_defects: list[dict[str, Any]] = []
    held_out_cases_by_category: dict[str, set[str]] = {
        cat: set() for cat in REQUIRED_CATEGORIES
    }

    cal_set = set(calibration_cases)

    for idx, entry in enumerate(raw_ballots):
        if not isinstance(entry, Mapping):
            invalid_ballot_errors.append(f"ballot[{idx}]: not an object")
            continue
        case_id = str(entry.get("case_id", "")).strip()
        split = str(entry.get("split", "")).strip()
        category = str(entry.get("category", "")).strip()
        comparator = str(entry.get("comparator", "")).strip()
        outcome = str(entry.get("outcome", "")).strip()

        if not case_id or not comparator:
            invalid_ballot_errors.append(f"ballot[{idx}]: missing case_id or comparator")
            continue
        if split != "held_out" or case_id in cal_set:
            split_contamination_ids.append(case_id)
            continue
        if category not in held_out_cases_by_category:
            invalid_ballot_errors.append(
                f"ballot[{idx}] ({case_id}): unknown category {category!r}"
            )
            continue
        if outcome not in ("fidelis_win", "tie", "comparator_win"):
            invalid_ballot_errors.append(
                f"ballot[{idx}] ({case_id}): invalid outcome {outcome!r}"
            )
            continue

        held_out_cases_by_category[category].add(case_id)

        defects = entry.get("critical_defects") or []
        if isinstance(defects, Sequence) and not isinstance(defects, (str, bytes)):
            for defect in defects:
                d_str = str(defect).strip()
                if d_str:
                    critical_defects.append(
                        {
                            "case_id": case_id,
                            "category": category,
                            "comparator": comparator,
                            "defect": d_str,
                            "recognized_critical_type": d_str in CRITICAL_DEFECT_TYPES,
                        }
                    )

        valid_ballots.append(
            {
                "case_id": case_id,
                "split": split,
                "category": category,
                "comparator": comparator,
                "outcome": outcome,
            }
        )

    required_comparators = [
        str(c)
        for c in (
            submission.get("required_comparators")
            or ["pinned_clarity", "dated_krea"]
        )
    ]

    by_comparator: dict[str, dict[str, Any]] = {}
    comparator_failures: list[str] = []
    for offset, comp in enumerate(required_comparators):
        comp_ballots = [b for b in valid_ballots if b["comparator"] == comp]
        summary = _summarize_ballots(
            comp_ballots, thresholds=thresholds, seed_offset=offset * 10
        )
        passed_pref = (
            summary["preference_plus_ties_rate"] is not None
            and summary["preference_plus_ties_rate"]
            >= thresholds.target_preference_plus_ties_min
        )
        passed_win = (
            summary["win_rate"] is not None
            and summary["win_rate"] >= thresholds.target_win_rate_min
        )
        summary["passed_thresholds"] = bool(passed_pref and passed_win)
        by_comparator[comp] = summary
        if not summary["passed_thresholds"]:
            comparator_failures.append(comp)

    by_category: dict[str, dict[str, Any]] = {}
    category_failures: list[str] = []
    missing_coverage_categories: list[str] = []
    for offset, cat in enumerate(REQUIRED_CATEGORIES):
        cat_ballots = [b for b in valid_ballots if b["category"] == cat]
        summary = _summarize_ballots(
            cat_ballots, thresholds=thresholds, seed_offset=500 + offset * 10
        )
        distinct_cases = len(held_out_cases_by_category[cat])
        summary["distinct_held_out_cases"] = distinct_cases
        summary["required_held_out_cases"] = thresholds.min_held_out_cases_per_category
        coverage_ok = distinct_cases >= thresholds.min_held_out_cases_per_category
        if not coverage_ok:
            missing_coverage_categories.append(cat)

        passed_cat_pref = (
            summary["preference_plus_ties_rate"] is not None
            and summary["preference_plus_ties_rate"]
            >= thresholds.category_preference_plus_ties_min
        )
        summary["passed_category_threshold"] = bool(passed_cat_pref and coverage_ok)
        by_category[cat] = summary
        if not passed_cat_pref:
            category_failures.append(cat)

    blocking_reasons: list[str] = []
    if not receipt_check["complete"]:
        blocking_reasons.append("incomplete_reproducibility_receipt")
    if not calibration_frozen:
        blocking_reasons.append("calibration_recipe_not_frozen")
    if split_contamination_ids:
        blocking_reasons.append("split_contamination_detected")
    if invalid_ballot_errors:
        blocking_reasons.append("invalid_ballot_records")
    if len(critical_defects) > thresholds.max_critical_defects:
        blocking_reasons.append("critical_fidelity_defects_present")
    if missing_coverage_categories:
        blocking_reasons.append("incomplete_held_out_category_coverage")
    if comparator_failures:
        blocking_reasons.append("comparator_threshold_not_met")
    if category_failures:
        blocking_reasons.append("category_threshold_not_met")

    signoff = submission.get("owner_creative_signoff") or {}
    signoff_status = str(signoff.get("status", "pending")).strip()
    reviewer = signoff.get("reviewer")
    signed_at = signoff.get("signed_at")
    owner_approved = (
        signoff_status == "approved"
        and bool(reviewer)
        and bool(signed_at)
    )

    quantitative_gates_passed = len(blocking_reasons) == 0

    if not quantitative_gates_passed:
        if (
            missing_coverage_categories
            and len(valid_ballots) == 0
            and len(critical_defects) == 0
        ):
            overall_status = "blocked_incomplete_evidence"
        else:
            overall_status = "failed"
    elif not owner_approved:
        overall_status = "awaiting_owner_signoff"
    else:
        overall_status = "accepted"

    report_payload = {
        "schema_version": SCHEMA_VERSION,
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "overall_status": overall_status,
        "quantitative_gates_passed": quantitative_gates_passed,
        "owner_creative_signoff": {
            "status": signoff_status,
            "approved": owner_approved,
            "reviewer": reviewer,
            "signed_at": signed_at,
            "notes": signoff.get("notes"),
        },
        "thresholds": {
            "target_preference_plus_ties_min": thresholds.target_preference_plus_ties_min,
            "target_win_rate_min": thresholds.target_win_rate_min,
            "category_preference_plus_ties_min": thresholds.category_preference_plus_ties_min,
            "min_held_out_cases_per_category": thresholds.min_held_out_cases_per_category,
            "max_critical_defects": thresholds.max_critical_defects,
        },
        "reproducibility_receipt": receipt_check,
        "calibration": {
            "recipe_frozen": calibration_frozen,
            "calibration_case_count": len(calibration_cases),
            "split_contamination_ids": sorted(set(split_contamination_ids)),
        },
        "critical_defect_count": len(critical_defects),
        "critical_defects": critical_defects,
        "comparator_results": by_comparator,
        "comparator_failures": comparator_failures,
        "category_results": by_category,
        "category_failures": category_failures,
        "missing_coverage_categories": missing_coverage_categories,
        "invalid_ballot_errors": invalid_ballot_errors,
        "blocking_reasons": blocking_reasons,
    }
    report_digest = hashlib.sha256(
        json.dumps(report_payload, sort_keys=True).encode("utf-8")
    ).hexdigest()
    report_payload["report_sha256"] = report_digest
    return report_payload
