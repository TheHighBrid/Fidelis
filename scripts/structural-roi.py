#!/usr/bin/env python3
"""Lock or inspect explicit structural rectangles in a saved Studio job."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fidelis.postprocess.regions import RegionBlend
from fidelis.studio.store import JobStore


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("inspect", "lock"))
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--job", required=True)
    parser.add_argument("--expected-revision", type=int, required=True)
    parser.add_argument("--roi", nargs=4, type=int, action="append", required=True,
                        metavar=("X", "Y", "WIDTH", "HEIGHT"))
    parser.add_argument("--target", choices=("texture", "master"), default="master",
                        help="Saved artifact to inspect against the precision base")
    args = parser.parse_args()
    try:
        store = JobStore(args.workspace)
        if args.operation == "inspect":
            result = store.inspect_structure(
                args.job, expected_revision=args.expected_revision, regions=args.roi, target=args.target,
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
