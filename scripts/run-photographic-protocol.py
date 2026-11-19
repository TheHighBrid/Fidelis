#!/usr/bin/env python3
"""CLI for Bot 05 photographic restoration protocol (and Bot 04 hook consumption)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from fidelis.eval.photographic_protocol import (
    ProtocolVerdict,
    evaluate_restoration_pair,
    list_rubrics,
)
from fidelis.eval.texture_eval_hooks import (
    TextureEvalRequest,
    evaluate_texture_candidate,
    hook_contract,
    write_protocol_receipt,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, help="Base / precision image path")
    parser.add_argument("--candidate", type=Path, help="Texture or composited candidate path")
    parser.add_argument(
        "--category",
        choices=["skin", "hair", "textiles", "products", "lettering"],
        help="Rubric category",
    )
    parser.add_argument("--case-id", default=None)
    parser.add_argument("--adapter-id", default=None, help="Optional Bot 04 adapter id")
    parser.add_argument("--json-out", type=Path, default=None)
    parser.add_argument("--list-rubrics", action="store_true")
    parser.add_argument("--show-hook-contract", action="store_true")
    args = parser.parse_args()

    if args.list_rubrics:
        print(json.dumps(list_rubrics(), indent=2))
        return 0
    if args.show_hook_contract:
        print(json.dumps(hook_contract(), indent=2))
        return 0

    if not args.base or not args.candidate or not args.category:
        parser.error("--base, --candidate, and --category are required unless listing rubrics/contract")

    if args.adapter_id:
        report = evaluate_texture_candidate(
            TextureEvalRequest(
                base_path=args.base,
                candidate_path=args.candidate,
                category=args.category,
                case_id=args.case_id,
                adapter_id=args.adapter_id,
            )
        )
    else:
        report = evaluate_restoration_pair(
            args.base,
            args.candidate,
            category=args.category,
            case_id=args.case_id,
        )

    payload = report.to_dict()
    text = json.dumps(payload, indent=2, sort_keys=True)
    print(text)
    if args.json_out:
        write_protocol_receipt(report, args.json_out.parent, filename=args.json_out.name)

    if report.verdict == ProtocolVerdict.FAIL:
        return 2
    if report.verdict == ProtocolVerdict.WARN:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
