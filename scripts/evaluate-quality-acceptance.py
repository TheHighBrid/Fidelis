#!/usr/bin/env python3
"""Evaluate calibration and blind held-out quality acceptance (F13 / MEL-66)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from fidelis.eval.quality_acceptance import (  # noqa: E402
    AcceptanceThresholds,
    evaluate_held_out_acceptance,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate held-out quality acceptance against F13 thresholds and reproducibility receipts."
    )
    parser.add_argument(
        "submission",
        type=Path,
        help="Path to held-out quality acceptance submission JSON",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional path to write evaluated report JSON",
    )
    parser.add_argument(
        "--require-owner-signoff",
        action="store_true",
        help="Exit non-zero unless owner_creative_signoff is explicitly approved",
    )
    args = parser.parse_args(argv)

    if not args.submission.is_file():
        print(
            json.dumps(
                {
                    "error": f"Submission file not found: {args.submission}",
                    "overall_status": "blocked_incomplete_evidence",
                },
                indent=2,
            ),
            file=sys.stderr,
        )
        return 2

    submission_data = json.loads(args.submission.read_text(encoding="utf-8"))
    report = evaluate_held_out_acceptance(
        submission_data,
        thresholds=AcceptanceThresholds(),
    )

    output_text = json.dumps(report, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output_text, encoding="utf-8")
    else:
        sys.stdout.write(output_text)

    if report["overall_status"] == "accepted":
        return 0
    if (
        report["overall_status"] == "awaiting_owner_signoff"
        and not args.require_owner_signoff
    ):
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
