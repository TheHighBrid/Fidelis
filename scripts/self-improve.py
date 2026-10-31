#!/usr/bin/env python3
"""CLI utility to execute the Fidelis Self-Improvement & Quality Calibration Cycle."""

import argparse
from pathlib import Path
import sys

# Ensure repository root is in sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from fidelis.tune.optimizer import SelfImprovementEngine


def main():
    parser = argparse.ArgumentParser(description="Run Fidelis Self-Improvement & Quality Calibration.")
    parser.add_argument(
        "-n", "--max-items",
        type=int,
        default=5,
        help="Maximum number of corpus items to calibrate across (default: 5)"
    )
    parser.add_argument(
        "-o", "--out-dir",
        type=str,
        default=None,
        help="Target directory for self-improvement outputs and reports"
    )
    args = parser.parse_args()

    work_dir = Path(args.out_dir) if args.out_dir else None
    engine = SelfImprovementEngine(work_dir=work_dir)

    print("\n=======================================================")
    print(" Fidelis Self-Improvement & Calibration Cycle")
    print("=======================================================")
    print(f"Target Corpus Items:    {args.max_items}")
    print(f"Work Directory:         {engine.work_dir}")
    print("Scanning orthogonal evaluation buckets...")

    summary = engine.run_self_improvement_cycle(max_items=args.max_items)

    print("\n-------------------------------------------------------")
    print(f"Items Evaluated:        {summary['items_evaluated']}")
    print(f"Total Trials Tested:    {summary['total_trials']}")
    print(f"Improvements Landed:    {summary['improvements_found']}")
    print(f"Calibrated Face w:      {summary['calibrated_face_fidelity_w']} (Anti-dollification)")
    print(f"Calibrated Text Unsharp:{summary['calibrated_text_strength']}")
    print(f"Quality Gate Status:    [{summary['quality_status']}]")
    print(f"HTML Visual Report:     {summary['report_path']}")
    print("=======================================================\n")


if __name__ == "__main__":
    main()
