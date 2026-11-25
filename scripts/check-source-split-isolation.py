#!/usr/bin/env python3
"""Emit a read-only JSON split preflight for explicit manifest paths."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from fidelis.eval.source_split_preflight import check_source_split_isolation


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, action="append", required=True,
                        help="Explicit JSON manifest path; repeat for each inventory")
    args = parser.parse_args()
    report = check_source_split_isolation(args.manifest)
    print(json.dumps(report, indent=2, allow_nan=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
