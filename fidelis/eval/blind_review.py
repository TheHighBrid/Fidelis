"""Deterministic blinded ballots and evidence-complete review scoring."""
from __future__ import annotations

import hashlib
import random
import shutil
from pathlib import Path
from typing import Any

import numpy as np


def build_blind_pairwise_manifest(
    comparison_report: dict[str, Any],
    candidate_a: str,
    candidate_b: str,
    *,
    split: str = "held_out",
    seed: int = 20261110,
    blind_dir: str | Path | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build blind randomized A/B comparison ballot keeping separate native PNG paths."""
    if candidate_a == candidate_b:
        raise ValueError("Pairwise comparison requires two distinct comparators")
    rng = random.Random(seed)  # nosec B311  # Non-cryptographic PRNG for deterministic evaluation
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
    pairing_key = "\0".join(sorted((candidate_a, candidate_b))).encode("utf-8")
    namespace = hashlib.sha256(pairing_key).hexdigest()[:16]
    for idx, case in enumerate(shuffled, start=1):
        pair_id = f"pair_{idx:03d}"
        swap = bool(rng.randint(0, 1))
        left_comp, right_comp = (candidate_b, candidate_a) if swap else (candidate_a, candidate_b)
        item, key = _publish_pair(case, pair_id, (left_comp, right_comp), blind_dir, f"{split}_{seed}", namespace)
        ballot_items.append(item)
        answer_key[pair_id] = key

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


def _publish_pair(case, pair_id, sides, blind_dir, split_seed, namespace):
    left_comp, right_comp = sides
    orig_left = Path(case["outputs"][left_comp]["output_path"])
    orig_right = Path(case["outputs"][right_comp]["output_path"])
    blind_parent = Path(blind_dir) if blind_dir is not None else orig_left.parent.parent / "blind_pairs" / split_seed
    # Pairing-specific opaque namespace prevents overwriting earlier ballots.
    pair_dir = blind_parent / f"pairing-{namespace}" / pair_id
    anon_left = pair_dir / f"option_left{orig_left.suffix or '.png'}"
    anon_right = pair_dir / f"option_right{orig_right.suffix or '.png'}"
    if orig_left.is_file() and orig_right.is_file():
        pair_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(orig_left, anon_left)
        shutil.copy2(orig_right, anon_right)
    item = {
        "pair_id": pair_id, "category": case["category"], "source_path": case["source_path"],
        "option_left": str(anon_left), "option_right": str(anon_right),
        "choice": None, "critical_defect_left": False, "critical_defect_right": False, "notes": "",
    }
    key = {
        "case_id": case["case_id"], "category": case["category"],
        "left": left_comp, "right": right_comp,
        "left_output_path": str(orig_left), "right_output_path": str(orig_right),
    }
    return item, key


def _bootstrap_ci(values: np.ndarray, *, n_resamples: int = 1000, seed: int = 2026) -> list[float]:
    if len(values) == 0:
        return [0.0, 0.0]
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(values), size=(n_resamples, len(values)))
    means = values[idx].mean(axis=1)
    lo, hi = np.percentile(means, [2.5, 97.5])
    return [round(float(lo), 4), round(float(hi), 4)]


def _collect_reviews(completed_ballot, answer_key, subject_comparator, target_comparator):
    mapping = answer_key.get("mapping", {})
    pref_ties: list[float] = []
    wins: list[float] = []
    by_category: dict[str, list[float]] = {}
    critical_defects_subject = 0
    unreviewed = 0
    requested_pair_ids = {
        pair_id
        for pair_id, meta in mapping.items()
        if {meta.get("left"), meta.get("right")}
        == {subject_comparator, target_comparator}
    }

    seen_pair_ids: set[str] = set()
    for entry in completed_ballot.get("items", []):
        pid = entry.get("pair_id")
        if pid in seen_pair_ids:
            raise ValueError(f"Duplicate pair_id {pid!r} in blind ballot")
        seen_pair_ids.add(pid)
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
        if entry.get(f"critical_defect_{subject_side}"):
            critical_defects_subject += 1

        is_win = 1.0 if choice == subject_side else 0.0
        is_pref_or_tie = 1.0 if choice in (subject_side, "tie") else 0.0
        wins.append(is_win)
        pref_ties.append(is_pref_or_tie)
        by_category.setdefault(meta["category"], []).append(is_pref_or_tie)

    # A reviewer may accidentally submit an exported subset rather than the
    # complete ballot.  Missing answer-key entries are unanswered evidence,
    # not a smaller sample that can qualify for a passing score.
    unreviewed += len(requested_pair_ids - seen_pair_ids)
    return wins, pref_ties, by_category, critical_defects_subject, unreviewed


def _score_reviews(wins, pref_ties, by_category, critical_defects_subject, n_bootstrap):
    n = len(wins)
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


def summarize_blind_reviews(
    completed_ballot: dict[str, Any],
    answer_key: dict[str, Any],
    *,
    subject_comparator: str,
    target_comparator: str,
    n_bootstrap: int = 1000,
) -> dict[str, Any]:
    """Score blind pairwise ballot with bootstrap CIs and proposed QUALITY_GATES thresholds."""
    wins, ties, categories, critical, unreviewed = _collect_reviews(completed_ballot, answer_key, subject_comparator, target_comparator)
    base = {"schema_version": 1, "subject": subject_comparator, "target": target_comparator, "sample_count": len(wins)}
    if not wins or unreviewed > 0:
        return {**base, "unreviewed_count": unreviewed,
                "status": "incomplete" if unreviewed > 0 else "unavailable",
                "preliminary_small_sample": True, "meets_proposed_thresholds": False}
    return {**base, **_score_reviews(wins, ties, categories, critical, n_bootstrap)}
