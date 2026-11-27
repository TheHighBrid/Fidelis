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
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fidelis.eval.source_split_preflight import collect_source_split_index

from fidelis.eval.quality_statistics import (
    _compute_inter_rater_agreement,
)
from fidelis.eval.quality_statistics import (
    bootstrap_95_ci as bootstrap_95_ci,
)
from fidelis.eval.quality_statistics import (  # noqa: F401
    cohen_kappa as cohen_kappa,
)
from fidelis.eval.quality_statistics import (
    krippendorff_alpha_nominal as krippendorff_alpha_nominal,
)
from fidelis.eval.quality_statistics import (
    wilson_95_ci as wilson_95_ci,
)

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
    require_automated_detail_gates: bool = False




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
        if val is None or val == {} or val == [] or (isinstance(val, str) and not val.strip()):
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


def _normalize_sha256(value: Any, field_name: str) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-fA-F]{64}", value) is None:
        raise ValueError(f"{field_name} must be a 64-character hex SHA-256")
    return value.lower()


def _normalize_ballot(entry):
    return {
        "case_id": str(entry.get("case_id", "")).strip(),
        "split": str(entry.get("split", "")).strip(),
        "category": str(entry.get("category", "")).strip(),
        "comparator": str(entry.get("comparator", "")).strip(),
        "outcome": str(entry.get("outcome", "")).strip(),
        "reviewer_id": entry.get("reviewer_id"),
    }


def _extract_declared_ballot_sha(entry: Mapping[str, Any], prefix: str) -> str | None:
    raw_direct = entry.get("source_sha256")
    source_obj = entry.get("source")
    if source_obj is not None and not isinstance(source_obj, Mapping):
        raise ValueError(f"{prefix}: source must be an object")
    raw_nested = source_obj.get("sha256") if isinstance(source_obj, Mapping) else None
    direct_sha = _normalize_sha256(raw_direct, f"{prefix}: source_sha256")
    nested_sha = _normalize_sha256(raw_nested, f"{prefix}: source.sha256")
    if direct_sha and nested_sha and direct_sha != nested_sha:
        raise ValueError(f"{prefix}: source_sha256 and source.sha256 disagree")
    return direct_sha or nested_sha


def _resolve_ballot_sha256(
    entry: Mapping[str, Any],
    case_id: str,
    idx: int,
    manifest_shas_by_id: Mapping[str, str],
) -> tuple[str | None, str | None]:
    prefix = f"ballot[{idx}] ({case_id})"
    try:
        declared_sha = _extract_declared_ballot_sha(entry, prefix)
    except ValueError as exc:
        return None, str(exc)
    manifest_sha = manifest_shas_by_id.get(case_id)
    if declared_sha and manifest_sha and declared_sha != manifest_sha:
        return None, f"{prefix}: declared source SHA disagrees with manifest SHA"
    return declared_sha or manifest_sha, None


def _ballot_error(ballot, idx, category_by_case, seen_ballot_keys):
    case_id, category, comparator, outcome = (ballot[k] for k in ("case_id", "category", "comparator", "outcome"))
    prefix = f"ballot[{idx}] ({case_id})"
    if category not in REQUIRED_CATEGORIES:
        return f"{prefix}: unknown category {category!r}"
    prior_category = category_by_case.get(case_id)
    if prior_category is not None and prior_category != category:
        return f"{prefix}: category conflicts with {prior_category!r}"
    if outcome not in ("fidelis_win", "tie", "comparator_win"):
        return f"{prefix}: invalid outcome {outcome!r}"
    ballot_key = (case_id, comparator, str(ballot.get("reviewer_id") or "").strip())
    if ballot_key in seen_ballot_keys:
        return f"{prefix}: duplicate ballot for ({case_id}, {comparator})"
    seen_ballot_keys.add(ballot_key)
    category_by_case[case_id] = category
    return None


def _collect_defects(entry, ballot, idx, invalid_ballot_errors, critical_defects):
    defects = entry.get("critical_defects", [])
    case_id = ballot["case_id"]
    prefix = f"ballot[{idx}] ({case_id})"
    if not isinstance(defects, Sequence) or isinstance(defects, (str, bytes)):
        invalid_ballot_errors.append(f"{prefix}: critical_defects must be a list")
        return False
    for defect in defects:
        if not isinstance(defect, str) or not defect.strip():
            invalid_ballot_errors.append(f"{prefix}: critical_defects must contain nonempty strings")
            continue
        d_str = defect.strip()
        critical_defects.append({
            "case_id": case_id, "category": ballot["category"], "comparator": ballot["comparator"],
            "defect": d_str, "recognized_critical_type": d_str in CRITICAL_DEFECT_TYPES,
        })
    return True


def _record_ballot_contamination(
    case_id: str,
    ballot_split: str,
    ballot_sha: str | None,
    cal_set: set[str],
    contaminated_shas: set[str],
    sha_aliases: Mapping[str, Sequence[Mapping[str, Any]]],
    split_contamination_ids: list[str],
    source_sha_contamination: list[dict[str, Any]],
) -> bool:
    sha_contaminated = ballot_sha is not None and ballot_sha in contaminated_shas
    if ballot_split == "held_out" and case_id not in cal_set and not sha_contaminated:
        return False
    split_contamination_ids.append(case_id)
    if sha_contaminated and ballot_sha is not None:
        source_sha_contamination.append({
            "case_id": case_id,
            "source_sha256": ballot_sha,
            "aliases": [str(a.get("id")) for a in sha_aliases.get(ballot_sha, ())],
        })
    return True


def _process_ballot_entry(
    idx: int,
    entry: Any,
    context: Mapping[str, Any],
    state: Mapping[str, Any],
) -> None:
    invalid_ballot_errors = state["invalid_ballot_errors"]
    if not isinstance(entry, Mapping):
        invalid_ballot_errors.append(f"ballot[{idx}]: not an object")
        return
    ballot = _normalize_ballot(entry)
    case_id = ballot["case_id"]
    if not case_id or not ballot["comparator"]:
        invalid_ballot_errors.append(f"ballot[{idx}]: missing case_id or comparator")
        return
    ballot_sha, sha_error = _resolve_ballot_sha256(entry, case_id, idx, context["id_to_sha"])
    if sha_error:
        invalid_ballot_errors.append(sha_error)
        return
    if _record_ballot_contamination(
        case_id, ballot["split"], ballot_sha, context["cal_set"], context["contaminated_shas"],
        context["sha_aliases"], state["split_contamination_ids"], state["source_sha_contamination"],
    ):
        return
    error = _ballot_error(ballot, idx, state["category_by_case"], state["seen_ballot_keys"])
    if error:
        invalid_ballot_errors.append(error)
        return
    state["held_out_cases_by_category"][ballot["category"]].add(case_id)
    if _collect_defects(entry, ballot, idx, invalid_ballot_errors, state["critical_defects"]):
        state["valid_ballots"].append(ballot)


def _collect_ballots(
    submission,
    calibration_cases,
    *,
    calibration_shas: Sequence[str] = (),
    conflict_shas: Sequence[str] = (),
    manifest_shas_by_id: Mapping[str, str] | None = None,
    aliases_by_sha: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
):
    raw_ballots = submission.get("held_out_ballots")
    if not isinstance(raw_ballots, Sequence):
        raw_ballots = []
    context = {
        "cal_set": set(calibration_cases),
        "contaminated_shas": set(calibration_shas) | set(conflict_shas),
        "id_to_sha": manifest_shas_by_id or {},
        "sha_aliases": aliases_by_sha or {},
    }
    state: dict[str, Any] = {
        "valid_ballots": [],
        "split_contamination_ids": [],
        "source_sha_contamination": [],
        "invalid_ballot_errors": [],
        "critical_defects": [],
        "held_out_cases_by_category": {cat: set() for cat in REQUIRED_CATEGORIES},
        "category_by_case": {},
        "seen_ballot_keys": set(),
    }
    for idx, entry in enumerate(raw_ballots):
        _process_ballot_entry(idx, entry, context, state)
    return (
        state["valid_ballots"],
        state["split_contamination_ids"],
        state["source_sha_contamination"],
        state["invalid_ballot_errors"],
        state["critical_defects"],
        state["held_out_cases_by_category"],
    )


def _required_comparators(submission):
    # Both flagship comparators are mandatory. Missing ballot evidence must
    # never redefine the evaluation protocol or silently pass coverage.
    mandatory_comparators = ("pinned_clarity", "dated_krea")
    explicit_comps = submission.get("required_comparators")
    declared_comparators = (
        [str(comp) for comp in explicit_comps]
        if isinstance(explicit_comps, (list, tuple)) else []
    )
    return list(dict.fromkeys(
        [*mandatory_comparators, *declared_comparators]
    ))


def _evaluate_comparators(submission, valid_ballots, thresholds):
    required_comparators = _required_comparators(submission)
    by_comparator: dict[str, dict[str, Any]] = {}
    comparator_failures: list[str] = []
    for offset, comp in enumerate(required_comparators):
        comp_ballots = [b for b in valid_ballots if b["comparator"] == comp]
        summary = _summarize_ballots(
            comp_ballots, thresholds=thresholds, seed_offset=offset * 10
        )
        comp_cases_by_cat = {
            cat: {b["case_id"] for b in comp_ballots if b["category"] == cat}
            for cat in REQUIRED_CATEGORIES
        }
        missing_comp_cats = [
            cat
            for cat in REQUIRED_CATEGORIES
            if len(comp_cases_by_cat[cat]) < thresholds.min_held_out_cases_per_category
        ]
        comp_coverage_ok = len(missing_comp_cats) == 0
        summary["distinct_held_out_cases"] = sum(
            len(cases) for cases in comp_cases_by_cat.values()
        )
        summary["required_held_out_cases"] = (
            len(REQUIRED_CATEGORIES) * thresholds.min_held_out_cases_per_category
        )
        summary["missing_coverage_categories"] = missing_comp_cats
        passed_pref = (
            summary["preference_plus_ties_rate"] is not None
            and summary["preference_plus_ties_rate"]
            >= thresholds.target_preference_plus_ties_min
        )
        passed_win = (
            summary["win_rate"] is not None
            and summary["win_rate"] >= thresholds.target_win_rate_min
        )
        summary["passed_thresholds"] = bool(
            passed_pref and passed_win and comp_coverage_ok
        )
        by_comparator[comp] = summary
        if not summary["passed_thresholds"]:
            comparator_failures.append(comp)
    return required_comparators, by_comparator, comparator_failures


def _evaluate_categories(valid_ballots, required_comparators, held_out_cases_by_category, thresholds):
    by_category: dict[str, dict[str, Any]] = {}
    category_failures: list[str] = []
    missing_coverage_categories: list[str] = []
    for offset, cat in enumerate(REQUIRED_CATEGORIES):
        cat_ballots = [
            b
            for b in valid_ballots
            if b["category"] == cat and b["comparator"] in required_comparators
        ]
        summary = _summarize_ballots(
            cat_ballots, thresholds=thresholds, seed_offset=500 + offset * 10
        )
        per_comp_counts = {
            comp: len({b["case_id"] for b in cat_ballots if b["comparator"] == comp})
            for comp in required_comparators
        }
        distinct_cases = (
            min(per_comp_counts.values())
            if per_comp_counts
            else len(held_out_cases_by_category[cat])
        )
        summary["distinct_held_out_cases"] = distinct_cases
        summary["distinct_held_out_cases_by_comparator"] = per_comp_counts
        summary["required_held_out_cases"] = thresholds.min_held_out_cases_per_category
        coverage_ok = (
            len(held_out_cases_by_category[cat])
            >= thresholds.min_held_out_cases_per_category
            and all(
                cnt >= thresholds.min_held_out_cases_per_category
                for cnt in per_comp_counts.values()
            )
        )
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
    return by_category, category_failures, missing_coverage_categories


def _automated_gate(submission, thresholds, blocking_reasons):
    raw_automated = submission.get("automated_metrics")
    automated_detail_gates: dict[str, Any] = {
        "required": thresholds.require_automated_detail_gates,
        "provided": isinstance(raw_automated, Mapping),
        "interior_texture_passed": None,
        "oversharpen_restraint_passed": None,
        "fabric_weave_passed": None,
        "hardware_seam_passed": None,
        "passed": None,
    }
    if isinstance(raw_automated, Mapping):
        f2_val = raw_automated.get("interior_texture_passed")
        f3_val = raw_automated.get("oversharpen_restraint_passed")
        f4_fab = raw_automated.get("fabric_weave_passed")
        f4_hw = raw_automated.get("hardware_seam_passed")
        automated_detail_gates.update(
            {
                "interior_texture_passed": f2_val,
                "oversharpen_restraint_passed": f3_val,
                "fabric_weave_passed": f4_fab,
                "hardware_seam_passed": f4_hw,
            }
        )
        if thresholds.require_automated_detail_gates:
            f2_ok = f2_val is True
            f3_ok = f3_val is True
            f4_ok = (f4_fab is True) and (f4_hw is True)
        else:
            f2_ok = f2_val is not False
            f3_ok = f3_val is not False
            f4_ok = (f4_fab is not False) and (f4_hw is not False)
        if not f2_ok:
            blocking_reasons.append("automated_f2_texture_regression")
        if not f3_ok:
            blocking_reasons.append("automated_f3_oversharpening_failed")
        if not f4_ok:
            blocking_reasons.append("automated_f4_fabric_or_hardware_failed")
        automated_detail_gates["passed"] = bool(f2_ok and f3_ok and f4_ok)
    elif thresholds.require_automated_detail_gates:
        blocking_reasons.append("missing_automated_detail_metrics")
        automated_detail_gates["passed"] = False
    return automated_detail_gates


def _creative_signoff(submission):
    signoff = submission.get("owner_creative_signoff") or submission.get("team_creative_signoff") or {}
    signoff_status = str(signoff.get("status", "pending")).strip()
    reviewer = signoff.get("reviewer") or signoff.get("team_lead") or signoff.get("delegate")
    signed_at = signoff.get("signed_at")
    owner_approved = (
        signoff_status == "approved"
        and bool(str(reviewer or "").strip())
        and bool(str(signed_at or "").strip())
    )
    return {
        "status": signoff_status,
        "approved": owner_approved,
        "reviewer": reviewer,
        "signed_at": signed_at,
        "notes": signoff.get("notes"),
    }


def _overall_status(
    blocking_reasons,
    missing_coverage_categories,
    valid_ballots,
    critical_defects,
    split_contamination_ids,
    invalid_ballot_errors,
    owner_approved,
    *,
    has_split_or_preflight_failure: bool = False,
):
    quantitative_gates_passed = len(blocking_reasons) == 0

    if not quantitative_gates_passed:
        if (
            missing_coverage_categories
            and len(valid_ballots) == 0
            and len(critical_defects) == 0
            and not split_contamination_ids
            and not invalid_ballot_errors
            and not has_split_or_preflight_failure
        ):
            overall_status = "blocked_incomplete_evidence"
        else:
            overall_status = "failed"
    elif not owner_approved:
        overall_status = "awaiting_owner_signoff"
    else:
        overall_status = "accepted"
    return overall_status, quantitative_gates_passed


def _finalize_report(payload, thresholds):
    report_payload = {
        "schema_version": SCHEMA_VERSION,
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        **payload,
        "thresholds": {
            "target_preference_plus_ties_min": thresholds.target_preference_plus_ties_min,
            "target_win_rate_min": thresholds.target_win_rate_min,
            "category_preference_plus_ties_min": thresholds.category_preference_plus_ties_min,
            "min_held_out_cases_per_category": thresholds.min_held_out_cases_per_category,
            "max_critical_defects": thresholds.max_critical_defects,
            "require_automated_detail_gates": thresholds.require_automated_detail_gates,
        },
    }
    report_payload["report_sha256"] = hashlib.sha256(json.dumps(report_payload, sort_keys=True).encode("utf-8")).hexdigest()
    return report_payload


def _parse_calibration_sha_list(raw_shas, cal_shas: set[str], cal_errors: list[str]) -> None:
    if raw_shas is None:
        return
    if not isinstance(raw_shas, Sequence) or isinstance(raw_shas, (str, bytes)):
        cal_errors.append("calibration_summary.source_sha256s must be a list")
        return
    for idx, raw_sha in enumerate(raw_shas):
        try:
            norm = _normalize_sha256(raw_sha, f"calibration_summary.source_sha256s[{idx}]")
        except ValueError as exc:
            cal_errors.append(str(exc))
            continue
        if norm:
            cal_shas.add(norm)


def _parse_calibration_hash_map(raw_case_hashes, cal_shas: set[str], cal_errors: list[str]) -> None:
    if raw_case_hashes is None:
        return
    if not isinstance(raw_case_hashes, Mapping):
        cal_errors.append("calibration_summary.case_source_hashes must be an object")
        return
    for cid, raw_sha in raw_case_hashes.items():
        try:
            norm = _normalize_sha256(raw_sha, f"calibration_summary.case_source_hashes[{cid!r}]")
        except ValueError as exc:
            cal_errors.append(str(exc))
            continue
        if norm:
            cal_shas.add(norm)


def _calibration_details(submission):
    calibration = submission.get("calibration_summary") or {}
    case_ids = [str(cid).strip() for cid in (calibration.get("case_ids") or []) if str(cid).strip()]
    cal_shas: set[str] = set()
    cal_errors: list[str] = []
    _parse_calibration_sha_list(calibration.get("source_sha256s"), cal_shas, cal_errors)
    _parse_calibration_hash_map(calibration.get("case_source_hashes"), cal_shas, cal_errors)
    return bool(calibration.get("recipe_frozen", False)), case_ids, sorted(cal_shas), cal_errors


def _manifest_split_context(manifest_paths: Sequence[str | Path] | None):
    if not manifest_paths:
        return None, {}, set(), set(), {}
    index = collect_source_split_index(manifest_paths)
    return (
        index,
        index["sha_by_id"],
        set(index["calibration_shas"]),
        set(index["conflict_shas"]),
        index["aliases_by_sha"],
    )


def _merge_manifest_conflicts(
    preflight_report: Mapping[str, Any] | None,
    split_contamination_ids: list[str],
    source_sha_contamination: list[dict[str, Any]],
) -> None:
    if not preflight_report or not preflight_report.get("conflicts"):
        return
    seen_contam = {(e["case_id"], e["source_sha256"]) for e in source_sha_contamination}
    for group in preflight_report["conflicts"]:
        sha = group["sha256"]
        alias_ids = [str(a["id"]) for a in group["aliases"]]
        for aid in alias_ids:
            if aid not in split_contamination_ids:
                split_contamination_ids.append(aid)
        if ("<manifest>", sha) not in seen_contam:
            source_sha_contamination.append({"case_id": "<manifest>", "source_sha256": sha, "aliases": alias_ids})


def _preflight_flags(split_index, valid_ballots) -> tuple[Any, bool, bool, bool]:
    if split_index is None:
        return None, False, False, False
    report = split_index["report"]
    return (
        report,
        bool(report["conflicts"]),
        bool(report["errors"] or split_index["id_hash_conflicts"]),
        bool(report["unknown_hashes"] and valid_ballots),
    )


def evaluate_held_out_acceptance(
    submission: Mapping[str, Any],
    *,
    thresholds: AcceptanceThresholds | None = None,
    manifest_paths: Sequence[str | Path] | None = None,
) -> dict[str, Any]:
    """Evaluate a calibration + blind held-out quality submission against F13 gates."""
    thresholds = AcceptanceThresholds() if thresholds is None else thresholds
    receipt_check = validate_reproducibility_receipt(submission.get("reproducibility_receipt"))
    calibration_frozen, calibration_cases, cal_shas, cal_errors = _calibration_details(submission)
    split_index, manifest_shas_by_id, manifest_cal_shas, conflict_shas, aliases_by_sha = (
        _manifest_split_context(manifest_paths)
    )
    all_cal_shas = sorted(set(cal_shas) | manifest_cal_shas)

    (
        valid_ballots,
        split_contamination_ids,
        source_sha_contamination,
        invalid_ballot_errors,
        critical_defects,
        held_out_cases_by_category,
    ) = _collect_ballots(
        submission,
        calibration_cases,
        calibration_shas=all_cal_shas,
        conflict_shas=sorted(conflict_shas),
        manifest_shas_by_id=manifest_shas_by_id,
        aliases_by_sha=aliases_by_sha,
    )
    all_invalid_errors = [*cal_errors, *invalid_ballot_errors]
    preflight_report, manifest_conflicts, manifest_errors, incomplete_manifest_hashes = _preflight_flags(
        split_index, valid_ballots
    )
    _merge_manifest_conflicts(preflight_report, split_contamination_ids, source_sha_contamination)

    required_comparators, by_comparator, comparator_failures = _evaluate_comparators(submission, valid_ballots, thresholds)
    by_category, category_failures, missing_coverage_categories = _evaluate_categories(valid_ballots, required_comparators, held_out_cases_by_category, thresholds)
    has_split_contamination = bool(split_contamination_ids or manifest_conflicts)
    blocking_reasons = [reason for condition, reason in (
        (not receipt_check["complete"], "incomplete_reproducibility_receipt"),
        (not calibration_frozen, "calibration_recipe_not_frozen"),
        (has_split_contamination, "split_contamination_detected"),
        (manifest_errors, "source_split_preflight_failed"),
        (incomplete_manifest_hashes, "incomplete_source_hash_coverage"),
        (all_invalid_errors, "invalid_ballot_records"),
        (len(critical_defects) > thresholds.max_critical_defects, "critical_fidelity_defects_present"),
        (missing_coverage_categories, "incomplete_held_out_category_coverage"),
        (comparator_failures, "comparator_threshold_not_met"),
        (category_failures, "category_threshold_not_met"),
    ) if condition]
    automated_detail_gates = _automated_gate(submission, thresholds, blocking_reasons)
    signoff = _creative_signoff(submission)
    overall_status, quantitative_gates_passed = _overall_status(
        blocking_reasons,
        missing_coverage_categories,
        valid_ballots,
        critical_defects,
        split_contamination_ids,
        all_invalid_errors,
        signoff["approved"],
        has_split_or_preflight_failure=has_split_contamination or manifest_errors or incomplete_manifest_hashes,
    )

    return _finalize_report({
        "overall_status": overall_status,
        "quantitative_gates_passed": quantitative_gates_passed,
        "owner_creative_signoff": signoff,
        "automated_detail_gates": automated_detail_gates,
        "reproducibility_receipt": receipt_check,
        "calibration": {
            "recipe_frozen": calibration_frozen,
            "calibration_case_count": len(calibration_cases),
            "calibration_source_sha256_count": len(all_cal_shas),
            "split_contamination_ids": sorted(set(split_contamination_ids)),
            "source_sha_contamination": source_sha_contamination,
        },
        "source_split_preflight": preflight_report,
        "critical_defect_count": len(critical_defects),
        "critical_defects": critical_defects,
        "comparator_results": by_comparator,
        "comparator_failures": comparator_failures,
        "category_results": by_category,
        "category_failures": category_failures,
        "inter_rater_agreement": _compute_inter_rater_agreement(valid_ballots),
        "missing_coverage_categories": missing_coverage_categories,
        "invalid_ballot_errors": all_invalid_errors,
        "blocking_reasons": blocking_reasons,
    }, thresholds)
