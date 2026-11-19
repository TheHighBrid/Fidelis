#!/usr/bin/env python3
"""Validate and summarize the F12-A 60-case corpus rights and ROI manifest."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from fidelis.eval.corpus_manifest import (
    ManifestValidationError,
    load_corpus_manifest,
    load_melato_corpus_manifest,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate Fidelis corpus rights, hashes, split, and ROI manifest."
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=REPO_ROOT / "experiments" / "corpus_manifest.json",
        help="Path to corpus manifest JSON (default: experiments/corpus_manifest.json)",
    )
    parser.add_argument(
        "--melato-manifest",
        type=Path,
        default=REPO_ROOT / "experiments" / "melato_corpus_manifest.json",
        help="Optional Melato companion inventory (default: experiments/melato_corpus_manifest.json)",
    )
    parser.add_argument(
        "--skip-melato",
        action="store_true",
        help="Skip Melato companion validation even if the file exists",
    )
    parser.add_argument(
        "--verify-files",
        action="store_true",
        help=(
            "Verify SHA-256 checksums and dimensions on disk for available corpus cases "
            "and regression assets. Off-repo Melato masters are verified only when "
            "--master-root is provided; otherwise those byte checks are skipped."
        ),
    )
    parser.add_argument(
        "--master-root",
        type=Path,
        default=None,
        help=(
            "Local directory containing Melato off-repo masters (e.g. "
            "/workspace/melato-corpus/fidelis). Used only with --verify-files."
        ),
    )
    parser.add_argument("--json", action="store_true", help="Emit validation summary as JSON")
    args = parser.parse_args()

    master_root = args.master_root.resolve() if args.master_root is not None else None

    try:
        _, summary = load_corpus_manifest(
            args.manifest.resolve(),
            repo_root=REPO_ROOT,
            verify_files=args.verify_files,
            master_root=master_root,
        )
        melato_summary = None
        melato_path = args.melato_manifest
        if not args.skip_melato and melato_path.is_file():
            _, melato_summary = load_melato_corpus_manifest(
                melato_path.resolve(),
                master_root=master_root,
                verify_files=args.verify_files,
            )
    except (ManifestValidationError, OSError, ValueError) as exc:
        print(f"Manifest validation failed: {exc}", file=sys.stderr)
        return 1

    payload = {"corpus": summary, "melato": melato_summary}
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        cal = summary["by_split"]["calibration"]
        held = summary["by_split"]["held_out"]
        print("Fidelis Corpus Rights & ROI Manifest Validated")
        print(
            f"Frozen 60-case coverage:  {summary['available_cases']}/{summary['total_slots']} "
            f"available ({summary['missing_cases']} missing, {summary['excluded_cases']} excluded)"
        )
        print(
            f"Split readiness:          calibration {cal['available']}/{cal['total']} | "
            f"held_out {held['available']}/{held['total']}"
        )
        print(
            f"Off-repo available slots: {summary.get('off_repo_available_cases', 0)} "
            f"(files_verified={summary.get('files_verified', 0)}, "
            f"skipped_no_master={summary.get('files_skipped_no_master', 0)})"
        )
        print(
            f"Regression fixtures/crops:{summary['regression_assets_count']} tracked "
            f"(counts_toward_60_case_corpus=false; verified={summary['regression_assets_verified']})"
        )
        if melato_summary is not None:
            print(
                f"Melato companion:         {melato_summary['total_assets']} assets | "
                f"GT {melato_summary['ground_truth_eligible']} | "
                f"non-GT {melato_summary['non_ground_truth']} | "
                f"verified={melato_summary['files_verified']} "
                f"skipped_no_master={melato_summary['files_skipped_no_master']}"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
