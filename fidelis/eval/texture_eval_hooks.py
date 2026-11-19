"""Thin evaluation hooks for Bot 04 zero-cost texture restoration candidates.

Bot 04 owns texture generation. Bot 05 owns photographic quality evaluation.
This module is the only intended cross-lane interface:

    from fidelis.eval.texture_eval_hooks import TextureEvalRequest, evaluate_texture_candidate

    report = evaluate_texture_candidate(
        TextureEvalRequest(
            case_id="synthetic_skin_plastic",
            base_path="base.png",
            candidate_path="texture_or_composited.png",
            category="skin",
        )
    )
    path = write_protocol_receipt(report, out_dir)

Do not edit texture model code from this lane. Do not claim production-corpus
scores until experiments/corpus_manifest.json marks cases rights-cleared and
available.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from fidelis.eval.photographic_protocol import (
    PROTOCOL_ID,
    PROTOCOL_VERSION,
    ProtocolReport,
    RubricCategory,
    evaluate_restoration_pair,
    list_rubrics,
)

PathLike = Union[str, Path]


@dataclass
class TextureEvalRequest:
    """Inputs Bot 04 (or any texture adapter) supplies for protocol evaluation."""

    base_path: PathLike
    candidate_path: PathLike
    category: str  # skin | hair | textiles | products | lettering
    case_id: Optional[str] = None
    protected_mask_path: Optional[PathLike] = None
    known_text: List[str] = field(default_factory=list)
    source_sha256: Optional[str] = None
    candidate_sha256: Optional[str] = None
    adapter_id: Optional[str] = None
    notes: List[str] = field(default_factory=list)


HOOK_CONTRACT: Dict[str, Any] = {
    "hook_id": "fidelis.bot05.texture_eval_hooks",
    "protocol_id": PROTOCOL_ID,
    "protocol_version": PROTOCOL_VERSION,
    "owner_lane": "Bot 05 photographic quality",
    "consumer_lane": "Bot 04 zero-cost texture restoration",
    "required_fields": [
        "base_path",
        "candidate_path",
        "category",
    ],
    "optional_fields": [
        "case_id",
        "protected_mask_path",
        "known_text",
        "source_sha256",
        "candidate_sha256",
        "adapter_id",
        "notes",
    ],
    "categories": [c.value for c in RubricCategory],
    "receipt_evidence_level": "E1",
    "production_corpus_gate": (
        "is_production_corpus remains false until corpus_manifest availability "
        "and rights.cleared are true for the case_id"
    ),
    "rubrics": list_rubrics(),
}


def evaluate_texture_candidate(request: TextureEvalRequest) -> ProtocolReport:
    """Run the photographic protocol on a Bot 04 (or any) texture candidate."""
    report = evaluate_restoration_pair(
        request.base_path,
        request.candidate_path,
        category=request.category,
        case_id=request.case_id,
        is_production_corpus=False,
    )
    if request.adapter_id:
        report.notes.append(f"adapter_id={request.adapter_id}")
    if request.known_text:
        report.notes.append(f"known_text={list(request.known_text)}")
    if request.protected_mask_path:
        report.notes.append(
            "protected_mask_path supplied; exact protected-pixel equality remains "
            "Studio compositor responsibility (out of Bot 05 protocol scope)."
        )
    for note in request.notes:
        report.notes.append(note)
    return report


def write_protocol_receipt(report: ProtocolReport, out_dir: PathLike, *, filename: Optional[str] = None) -> Path:
    """Write a JSON protocol receipt Bot 04 / CI can archive."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    name = filename or f"protocol_receipt_{(report.case_id or 'anonymous')}.json"
    path = out / name
    payload = report.to_dict()
    payload["hook_contract_id"] = HOOK_CONTRACT["hook_id"]
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def hook_contract() -> Dict[str, Any]:
    """Return the static Bot 04 ↔ Bot 05 evaluation contract."""
    return dict(HOOK_CONTRACT)
