#!/usr/bin/env python3
"""Propose, inspect, or lock structural rectangles in a saved Studio job."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fidelis.postprocess.regions import RegionBlend
from fidelis.studio.store import JobStore


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("inspect", "lock", "propose"))
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--job", required=True)
    parser.add_argument("--expected-revision", type=int, required=True)
    parser.add_argument("--roi", nargs=4, type=int, action="append",
                        metavar=("X", "Y", "WIDTH", "HEIGHT"))
    parser.add_argument("--target", choices=("texture", "master"), default=None,
                        help="Saved artifact to inspect against the precision base")
    parser.add_argument("--max-proposals", type=int, default=16,
                        help="Maximum structural candidate boxes returned by propose (1..64)")
    parser.add_argument("--cell-size", type=int, default=16,
                        help="Cell grid size in pixels for propose edge clustering")
    parser.add_argument("--min-edges-per-cell", type=int, default=None,
                        help="Minimum strong luminance edges per cell for propose (default: adaptive p80, min 16)")
    parser.add_argument("--min-area", type=int, default=64,
                        help="Minimum proposed rectangle area in pixels")
    parser.add_argument("--padding", type=int, default=4,
                        help="Source-grid padding around proposed clusters in pixels")
    args = parser.parse_args()
    try:
        store = JobStore(args.workspace)
        if args.operation == "propose":
            result = store.propose_structure(
                args.job,
                expected_revision=args.expected_revision,
                target=args.target,
                options={
                    "max_proposals": args.max_proposals,
                    "cell_size": args.cell_size,
                    "min_edges_per_cell": args.min_edges_per_cell,
                    "min_area": args.min_area,
                    "padding": args.padding,
                },
            )
        else:
            if not args.roi:
                raise ValueError("--roi is required for inspect and lock")
            if args.operation == "inspect":
                result = store.inspect_structure(
                    args.job,
                    expected_revision=args.expected_revision,
                    regions=args.roi,
                    target=args.target or "master",
                )
            else:
                job = store.get(args.job)
                updated = store.reblend(
                    args.job, expected_revision=args.expected_revision,
                    blend=RegionBlend(**job["blend"]), lock_regions=args.roi,
                )
                result = {key: updated[key] for key in ("id", "revision", "last_structural_lock")}
        print(json.dumps(result, indent=2, allow_nan=False))
    except (ValueError, OSError, KeyError) as error:
        parser.exit(2, f"structural-roi: {error}\n")


if __name__ == "__main__":
    main()
