"""Photographic restoration quality protocol (Bot 05 / F12 evaluation lane).

Sharpness alone is never restoration quality. This module implements a repeatable
comparison protocol and category rubrics for skin, hair, textiles, products, and
lettering. It emits structural defect flags and protocol receipts. It does NOT
fabricate LPIPS, competitor-parity scores, or creative acceptance.

Synthetic fixtures under tests/fixtures/photographic_protocol/ exercise the
protocol in CI. They are NOT the production rights-cleared 60-case corpus.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageFilter


class RubricCategory(str, Enum):
    SKIN = "skin"
    HAIR = "hair"
    TEXTILES = "textiles"
    PRODUCTS = "products"
    LETTERING = "lettering"


class DefectCode(str, Enum):
    PLASTIC_SKIN = "plastic_skin"
    EXAGGERATED_TEXTURE = "exaggerated_texture"
    INVENTED_PRODUCT_DETAIL = "invented_product_detail"
    LETTERING_MUTATION = "lettering_mutation"
    SHARPNESS_WITHOUT_RESTORATION = "sharpness_without_restoration"
    BACKGROUND_INVENTION = "background_invention"
    IDENTITY_DRIFT = "identity_drift"
    WEAVE_HALLUCINATION = "weave_hallucination"


class ProtocolVerdict(str, Enum):
    PASSED = "PASSED"
    WARN = "WARN"
    FAIL = "FAIL"
    INCONCLUSIVE = "INCONCLUSIVE"


PathLike = str | Path


@dataclass(frozen=True)
class RubricCriterion:
    criterion_id: str
    category: RubricCategory
    statement: str
    fail_defect: DefectCode
    notes: str = ""


# Explicit rubrics: restoration quality ≠ sharpness.
RUBRICS: tuple[RubricCriterion, ...] = (
    RubricCriterion(
        "skin_microtexture_preserved",
        RubricCategory.SKIN,
        "Natural mid-frequency skin grain and pores remain; waxy/plastic smoothing is a defect even if edges look crisp.",
        DefectCode.PLASTIC_SKIN,
        "Do not reward unsharp-mask halos as skin recovery.",
    ),
    RubricCriterion(
        "skin_no_repeated_pores",
        RubricCategory.SKIN,
        "No tiled/repeated pore stamps or synthetic micro-pattern that raises edge energy without identity-consistent texture.",
        DefectCode.EXAGGERATED_TEXTURE,
    ),
    RubricCriterion(
        "hair_strand_continuity",
        RubricCategory.HAIR,
        "Strand edges stay continuous without glitter noise or invented flyaways that only increase high-frequency energy.",
        DefectCode.EXAGGERATED_TEXTURE,
    ),
    RubricCriterion(
        "textile_weave_coherence",
        RubricCategory.TEXTILES,
        "Weave direction and period remain coherent; invented checkerboards or over-amplified yarn are defects.",
        DefectCode.WEAVE_HALLUCINATION,
    ),
    RubricCriterion(
        "product_construction_locked",
        RubricCategory.PRODUCTS,
        "Seams, zippers, hardware, and product contours must not gain new features absent from the base.",
        DefectCode.INVENTED_PRODUCT_DETAIL,
    ),
    RubricCriterion(
        "lettering_stroke_integrity",
        RubricCategory.LETTERING,
        "Glyph strokes, counters, and logo geometry stay registered; sharpness that rewrites characters fails.",
        DefectCode.LETTERING_MUTATION,
    ),
    RubricCriterion(
        "no_sharpness_proxy",
        RubricCategory.PRODUCTS,
        "A rise in Laplacian/edge energy without gradient coherence or mid-band fidelity is sharpness-without-restoration.",
        DefectCode.SHARPNESS_WITHOUT_RESTORATION,
        "Applies across categories; listed under products for packshot macros.",
    ),
)


@dataclass
class DefectFinding:
    code: DefectCode
    severity: str  # blocking | warning
    evidence: dict[str, Any]
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code.value,
            "severity": self.severity,
            "evidence": self.evidence,
            "message": self.message,
        }


@dataclass
class ProtocolReport:
    protocol_id: str
    protocol_version: str
    category: RubricCategory
    verdict: ProtocolVerdict
    defects: list[DefectFinding] = field(default_factory=list)
    metrics: dict[str, float] = field(default_factory=dict)
    rubrics_applied: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    evidence_level: str = "E1"
    is_production_corpus: bool = False
    case_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "protocol_id": self.protocol_id,
            "protocol_version": self.protocol_version,
            "category": self.category.value,
            "verdict": self.verdict.value,
            "defects": [d.to_dict() for d in self.defects],
            "metrics": self.metrics,
            "rubrics_applied": list(self.rubrics_applied),
            "notes": list(self.notes),
            "evidence_level": self.evidence_level,
            "is_production_corpus": self.is_production_corpus,
            "case_id": self.case_id,
            "disclaimer": (
                "Structural/protocol evidence only. Not creative acceptance, "
                "not competitor parity, not a fabricated quality score."
            ),
        }

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)


PROTOCOL_ID = "fidelis.photographic_restoration_protocol"
PROTOCOL_VERSION = "1.0.0"


def _load_rgb(path: PathLike) -> np.ndarray:
    img = Image.open(str(path)).convert("RGB")
    return np.asarray(img, dtype=np.float32)


def _to_gray(rgb: np.ndarray) -> np.ndarray:
    return rgb[:, :, 0] * 0.2989 + rgb[:, :, 1] * 0.5870 + rgb[:, :, 2] * 0.1140


def _resize_match(base: np.ndarray, other: np.ndarray) -> np.ndarray:
    if base.shape[:2] == other.shape[:2]:
        return other
    h, w = base.shape[:2]
    pil = Image.fromarray(np.clip(other, 0, 255).astype(np.uint8))
    return np.asarray(pil.resize((w, h), Image.Resampling.BICUBIC), dtype=np.float32)


def _laplacian_energy(gray: np.ndarray) -> float:
    # Discrete Laplacian via second differences (no OpenCV dependency here).
    c = gray[1:-1, 1:-1]
    lap = (
        gray[1:-1, 2:]
        + gray[1:-1, :-2]
        + gray[2:, 1:-1]
        + gray[:-2, 1:-1]
        - 4.0 * c
    )
    return float(np.std(lap))


def _local_variance(gray: np.ndarray, win: int = 7) -> np.ndarray:
    if win % 2 == 0:
        raise ValueError("win must be odd")
    pad = win // 2
    g = np.pad(gray, pad, mode="edge")
    # Integral-image style box mean via cumsum.
    def box_sum(arr: np.ndarray) -> np.ndarray:
        c = np.pad(arr, ((1, 0), (1, 0)), mode="constant")
        ii = c.cumsum(0).cumsum(1)
        return (
            ii[win:, win:]
            - ii[:-win, win:]
            - ii[win:, :-win]
            + ii[:-win, :-win]
        )

    s1 = box_sum(g)
    s2 = box_sum(g * g)
    area = float(win * win)
    mean = s1 / area
    var = np.maximum(s2 / area - mean * mean, 0.0)
    return var


def _gradient_coherence(base_gray: np.ndarray, out_gray: np.ndarray) -> float:
    gx1, gy1 = np.gradient(base_gray)
    gx2, gy2 = np.gradient(out_gray)
    dot = gx1 * gx2 + gy1 * gy2
    n1 = np.sqrt(gx1 * gx1 + gy1 * gy1) + 1e-4
    n2 = np.sqrt(gx2 * gx2 + gy2 * gy2) + 1e-4
    cos = dot / (n1 * n2)
    edge = n1 > 8.0
    if np.any(edge):
        return float(np.mean(np.clip(cos[edge], 0.0, 1.0)) * 100.0)
    return float(np.mean(np.clip(cos, 0.0, 1.0)) * 100.0)


def _midband_energy(gray: np.ndarray) -> float:
    # Difference of Gaussians approximates mid-frequency band without claiming LPIPS.
    pil = Image.fromarray(np.clip(gray, 0, 255).astype(np.uint8), mode="L")
    blur_a = np.asarray(pil.filter(ImageFilter.GaussianBlur(radius=1.0)), dtype=np.float32)
    blur_b = np.asarray(pil.filter(ImageFilter.GaussianBlur(radius=3.0)), dtype=np.float32)
    return float(np.std(blur_a - blur_b))


def _binary_letter_mask(gray: np.ndarray, threshold: float = 140.0) -> np.ndarray:
    # Synthetic lettering fixtures use dark glyphs on light fields.
    return gray < threshold


def _mask_iou(a: np.ndarray, b: np.ndarray) -> float:
    inter = np.logical_and(a, b).sum()
    union = np.logical_or(a, b).sum()
    if union == 0:
        return 1.0
    return float(inter / union)


def rubrics_for(category: RubricCategory) -> list[RubricCriterion]:
    shared = [r for r in RUBRICS if r.criterion_id == "no_sharpness_proxy"]
    specific = [r for r in RUBRICS if r.category == category and r.criterion_id != "no_sharpness_proxy"]
    # Always include the cross-cutting sharpness rule.
    out = specific + [r for r in shared if r not in specific]
    return out



def _compute_pair_metrics(base: np.ndarray, cand: np.ndarray) -> dict[str, float]:
    g0 = _to_gray(base)
    g1 = _to_gray(cand)
    lap0 = _laplacian_energy(g0)
    lap1 = _laplacian_energy(g1)
    sharp_gain = lap1 / max(lap0, 1e-4)
    mid0 = _midband_energy(g0)
    mid1 = _midband_energy(g1)
    mid_ratio = mid1 / max(mid0, 1e-4)
    coherence = _gradient_coherence(g0, g1)
    local_var0 = float(np.mean(_local_variance(g0)))
    local_var1 = float(np.mean(_local_variance(g1)))
    var_ratio = local_var1 / max(local_var0, 1e-4)
    gx0, gy0 = np.gradient(g0)
    flat = np.sqrt(gx0 * gx0 + gy0 * gy0) < 2.0
    invented_flat = 0.0
    if np.any(flat):
        gx1, gy1 = np.gradient(g1)
        invented_flat = float(np.mean(np.sqrt(gx1[flat] ** 2 + gy1[flat] ** 2)))
    abs_diff = float(np.mean(np.abs(g1 - g0)))
    calm = np.sqrt(gx0 * gx0 + gy0 * gy0) < 3.0
    new_structure = 0.0
    if np.any(calm):
        gx1, gy1 = np.gradient(g1)
        cand_edge = np.sqrt(gx1 * gx1 + gy1 * gy1)
        new_structure = float(np.mean(cand_edge[calm] > 18.0) * 100.0)
    metrics = {
        "laplacian_energy_base": round(lap0, 4),
        "laplacian_energy_candidate": round(lap1, 4),
        "sharpness_gain": round(sharp_gain, 4),
        "midband_energy_base": round(mid0, 4),
        "midband_energy_candidate": round(mid1, 4),
        "midband_ratio": round(mid_ratio, 4),
        "gradient_coherence_pct": round(coherence, 2),
        "local_variance_ratio": round(var_ratio, 4),
        "flat_region_invention_energy": round(invented_flat, 4),
        "mean_abs_diff": round(abs_diff, 4),
        "new_structure_in_calm_pct": round(new_structure, 4),
        "letter_mask_iou": round(_mask_iou(_binary_letter_mask(g0), _binary_letter_mask(g1)), 4),
    }
    return metrics


def _collect_defects(category: RubricCategory, metrics: dict[str, float]) -> list[DefectFinding]:
    defects: list[DefectFinding] = []
    sharp_gain = metrics["sharpness_gain"]
    coherence = metrics["gradient_coherence_pct"]
    mid_ratio = metrics["midband_ratio"]
    var_ratio = metrics["local_variance_ratio"]
    invented_flat = metrics["flat_region_invention_energy"]
    new_structure = metrics["new_structure_in_calm_pct"]
    abs_diff = metrics["mean_abs_diff"]

    if sharp_gain >= 1.35 and (coherence < 88.0 or mid_ratio < 0.85):
        defects.append(
            DefectFinding(
                DefectCode.SHARPNESS_WITHOUT_RESTORATION,
                "blocking",
                {
                    "sharpness_gain": sharp_gain,
                    "gradient_coherence_pct": coherence,
                    "midband_ratio": mid_ratio,
                },
                "Edge energy rose without mid-band fidelity / gradient coherence; sharpness is not restoration.",
            )
        )

    if category == RubricCategory.SKIN:
        if mid_ratio < 0.75 and var_ratio < 0.80:
            defects.append(
                DefectFinding(
                    DefectCode.PLASTIC_SKIN,
                    "blocking",
                    {"midband_ratio": mid_ratio, "local_variance_ratio": var_ratio},
                    "Skin mid-frequency grain collapsed (plastic / beauty-smooth signature).",
                )
            )
        if sharp_gain >= 1.5 and mid_ratio > 1.25 and coherence < 90.0:
            defects.append(
                DefectFinding(
                    DefectCode.EXAGGERATED_TEXTURE,
                    "blocking",
                    {"sharpness_gain": sharp_gain, "midband_ratio": mid_ratio},
                    "Exaggerated skin micro-texture / pore stamp risk.",
                )
            )

    if category == RubricCategory.HAIR and sharp_gain >= 1.25 and coherence < 92.0:
        defects.append(
            DefectFinding(
                DefectCode.EXAGGERATED_TEXTURE,
                "blocking",
                {"sharpness_gain": sharp_gain, "gradient_coherence_pct": coherence},
                "Hair high-frequency glitter / invented strand noise.",
            )
        )

    if category == RubricCategory.TEXTILES and sharp_gain >= 1.45 and (coherence < 87.0 or invented_flat > 6.0):
        defects.append(
            DefectFinding(
                DefectCode.WEAVE_HALLUCINATION,
                "blocking",
                {
                    "sharpness_gain": sharp_gain,
                    "gradient_coherence_pct": coherence,
                    "flat_region_invention_energy": invented_flat,
                },
                "Textile weave amplification looks invented rather than restored.",
            )
        )

    if category == RubricCategory.PRODUCTS and (
        invented_flat > 8.0
        or new_structure >= 1.5
        or abs_diff >= 2.5
        or (sharp_gain >= 1.3 and coherence < 85.0)
    ):
        defects.append(
            DefectFinding(
                DefectCode.INVENTED_PRODUCT_DETAIL,
                "blocking",
                {
                    "flat_region_invention_energy": invented_flat,
                    "new_structure_in_calm_pct": new_structure,
                    "mean_abs_diff": abs_diff,
                    "gradient_coherence_pct": coherence,
                },
                "New high-contrast structure appeared where the base was flat/stable (invented product detail).",
            )
        )

    if category == RubricCategory.LETTERING:
        iou = metrics["letter_mask_iou"]
        if iou < 0.92 or (sharp_gain >= 1.25 and coherence < 90.0):
            defects.append(
                DefectFinding(
                    DefectCode.LETTERING_MUTATION,
                    "blocking",
                    {"letter_mask_iou": iou, "sharpness_gain": sharp_gain},
                    "Lettering/logo stroke geometry drifted; crispness that rewrites glyphs fails.",
                )
            )

    if invented_flat > 12.0 and category != RubricCategory.PRODUCTS:
        defects.append(
            DefectFinding(
                DefectCode.BACKGROUND_INVENTION,
                "warning",
                {"flat_region_invention_energy": invented_flat},
                "Spurious energy in formerly flat regions (background invention risk).",
            )
        )
    return defects


def evaluate_restoration_pair(
    base_path: PathLike,
    candidate_path: PathLike,
    *,
    category: str | RubricCategory,
    case_id: str | None = None,
    is_production_corpus: bool = False,
) -> ProtocolReport:
    """Compare base vs candidate and emit a protocol receipt with defect flags."""
    cat = RubricCategory(category) if isinstance(category, str) else category
    if is_production_corpus:
        raise ValueError(
            "Refusing to mark synthetic/protocol runs as production corpus. "
            "Populate experiments/corpus_manifest.json with cleared rights first."
        )

    base = _load_rgb(base_path)
    cand = _resize_match(base, _load_rgb(candidate_path))
    full_metrics = _compute_pair_metrics(base, cand)
    defects = _collect_defects(cat, full_metrics)
    if cat != RubricCategory.LETTERING:
        defects = [d for d in defects if d.code != DefectCode.LETTERING_MUTATION]
        metrics = {k: v for k, v in full_metrics.items() if k != "letter_mask_iou"}
    else:
        metrics = full_metrics

    applied = [r.criterion_id for r in rubrics_for(cat)]
    blocking = [d for d in defects if d.severity == "blocking"]
    if blocking:
        verdict = ProtocolVerdict.FAIL
    elif defects:
        verdict = ProtocolVerdict.WARN
    else:
        verdict = ProtocolVerdict.PASSED

    notes = [
        "Sharpness/edge-energy gain is never sufficient for PASSED.",
        "Synthetic protocol fixtures are not the rights-cleared production corpus.",
        f"Rubrics applied: {', '.join(applied)}",
    ]
    return ProtocolReport(
        protocol_id=PROTOCOL_ID,
        protocol_version=PROTOCOL_VERSION,
        category=cat,
        verdict=verdict,
        defects=defects,
        metrics=metrics,
        rubrics_applied=applied,
        notes=notes,
        evidence_level="E1",
        is_production_corpus=False,
        case_id=case_id,
    )



def list_rubrics() -> list[dict[str, Any]]:
    return [
        {
            "criterion_id": r.criterion_id,
            "category": r.category.value,
            "statement": r.statement,
            "fail_defect": r.fail_defect.value,
            "notes": r.notes,
        }
        for r in RUBRICS
    ]
