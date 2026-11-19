"""Statistical confidence and inter-rater agreement for held-out quality ballots."""
from __future__ import annotations

import math
import random
from collections.abc import Mapping, Sequence
from typing import Any


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
    rng = random.Random(seed)  # nosec B311  # Non-cryptographic PRNG for deterministic bootstrap
    means: list[float] = []
    for _ in range(resamples):
        sample_sum = sum(outcomes[rng.randrange(n)] for _ in range(n))
        means.append(sample_sum / n)
    means.sort()
    lo_idx = max(0, math.floor(0.025 * (resamples - 1)))
    hi_idx = min(resamples - 1, math.ceil(0.975 * (resamples - 1)))
    return (round(means[lo_idx], 4), round(means[hi_idx], 4))


def cohen_kappa(rater_a: Sequence[str], rater_b: Sequence[str]) -> float | None:
    """Compute unweighted Cohen's kappa for two aligned categorical rating sequences."""
    if len(rater_a) != len(rater_b) or len(rater_a) == 0:
        return None
    n = len(rater_a)
    labels = sorted(set(rater_a) | set(rater_b))
    agreed = sum(1 for a, b in zip(rater_a, rater_b) if a == b)
    p_o = agreed / n
    p_e = 0.0
    for label in labels:
        ca = sum(1 for a in rater_a if a == label)
        cb = sum(1 for b in rater_b if b == label)
        p_e += (ca / n) * (cb / n)
    if abs(1.0 - p_e) < 1e-12:
        return 1.0 if abs(1.0 - p_o) < 1e-12 else 0.0
    return round((p_o - p_e) / (1.0 - p_e), 4)


def krippendorff_alpha_nominal(
    item_ratings: Sequence[Sequence[str | None]],
) -> float | None:
    """Compute Krippendorff's alpha (nominal metric) across items rated by >= 2 reviewers."""
    pairable_units: list[list[str]] = []
    label_totals: dict[str, int] = {}
    total_pairable_values = 0

    for unit in item_ratings:
        valid = [str(r) for r in unit if r is not None and str(r) != ""]
        if len(valid) >= 2:
            pairable_units.append(valid)
            total_pairable_values += len(valid)
            for val in valid:
                label_totals[val] = label_totals.get(val, 0) + 1

    if total_pairable_values < 2 or not pairable_units:
        return None

    # Observed disagreement D_o across pairable units
    disagreed_within = 0.0
    for valid in pairable_units:
        m_u = len(valid)
        counts: dict[str, int] = {}
        for val in valid:
            counts[val] = counts.get(val, 0) + 1
        disagreed_pairs = sum(c * (m_u - c) for c in counts.values())
        disagreed_within += disagreed_pairs / (m_u - 1)
    d_o = disagreed_within / total_pairable_values

    # Expected disagreement D_e from marginal frequencies
    disagreed_expected_pairs = sum(
        n_c * (total_pairable_values - n_c) for n_c in label_totals.values()
    )
    d_e = disagreed_expected_pairs / (
        total_pairable_values * (total_pairable_values - 1)
    )
    if abs(d_e) < 1e-12:
        return 1.0 if abs(d_o) < 1e-12 else 0.0
    return round(1.0 - (d_o / d_e), 4)


def _compute_inter_rater_agreement(
    ballots: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Summarize inter-rater agreement (Cohen's kappa and Krippendorff's alpha) when reviewer_id is present."""
    by_item: dict[tuple[str, str], dict[str, str]] = {}
    reviewers: set[str] = set()
    for b in ballots:
        rev = b.get("reviewer_id")
        if rev is not None and str(rev).strip():
            r_id = str(rev).strip()
            reviewers.add(r_id)
            key = (str(b["case_id"]), str(b["comparator"]))
            by_item.setdefault(key, {})[r_id] = str(b["outcome"])

    sorted_reviewers = sorted(reviewers)
    overlapping_units = [
        [ratings.get(r) for r in sorted_reviewers]
        for _, ratings in sorted(by_item.items())
        if len(ratings) >= 2
    ]
    alpha = krippendorff_alpha_nominal(overlapping_units)
    kappa = None
    if len(sorted_reviewers) == 2:
        r0, r1 = sorted_reviewers
        paired_a: list[str] = []
        paired_b: list[str] = []
        for _, ratings in sorted(by_item.items()):
            if r0 in ratings and r1 in ratings:
                paired_a.append(ratings[r0])
                paired_b.append(ratings[r1])
        kappa = cohen_kappa(paired_a, paired_b)

    return {
        "reviewer_count": len(sorted_reviewers),
        "overlapping_pair_count": len(overlapping_units),
        "cohen_kappa": kappa,
        "krippendorff_alpha_nominal": alpha,
    }
