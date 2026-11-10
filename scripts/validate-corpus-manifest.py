#!/usr/bin/env python3
"""Validate and summarize the F12-A 60-case corpus rights and ROI manifest."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from fidelis.eval.corpus_manifest import (  # noqa: E402
    ManifestValidationError,
    load_corpus_manifest,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Fidelis corpus rights, hashes, split, and ROI manifest.")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=REPO_ROOT / "experiments" / "corpus_manifest.json",
        help="Path to corpus manifest JSON (default: experiments/corpus_manifest.json)",
    )
    parser.add_argument(
        "--verify-files",
        action="store_true",
        help="Verify SHA-256 checksums and PNG dimensions on disk for available corpus cases and regression assets",
    )
    parser.add_argument("--json", action="store_true", help="Emit validation summary as JSON")
    args = parser.parse_args()

    try:
        _, summary = load_corpus_manifest(
            args.manifest.resolve(),
            repo_root=REPO_ROOT,
            verify_files=args.verify_files,
        )
    except (ManifestValidationError, OSError, ValueError) as exc:
        print(f"Manifest validation failed: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        cal = summary["by_split"]["calibration"]
        held = summary["by_split"]["held_out"]
        print("Fidelis Corpus Rights & ROI Manifest Validated")
        print(f"Frozen 60-case coverage:  {summary['available_cases']}/{summary['total_slots']} available ({summary['missing_cases']} missing, {summary['excluded_cases']} excluded)")
        print(f"Split readiness:          calibration {cal['available']}/{cal['total']} | held_out {held['available']}/{held['total']}")
        print(f"Regression fixtures/crops:{summary['regression_assets_count']} tracked (counts_toward_60_case_corpus=false; verified={summary['regression_assets_verified']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
