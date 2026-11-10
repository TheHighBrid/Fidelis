#!/usr/bin/env python3
"""Validate candidate model provenance, weight hashes, and usage terms (F05-B / MEL-75)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from fidelis.studio.provenance import ProvenanceError, audit_model_provenance  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-home", type=Path, help="Optional FIDELIS_HOME path to inspect installed bytes")
    parser.add_argument("--json", action="store_true", help="Emit complete provenance & terms report as JSON")
    args = parser.parse_args()

    try:
        report = audit_model_provenance(REPO_ROOT, app_home=args.app_home)
    except (ProvenanceError, OSError, ValueError) as exc:
        print(f"Provenance audit failed: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        summary = report["catalog_summary"]
        by_prov = summary["by_provenance_status"]
        print("Fidelis Model Provenance & Terms Audit")
        print(f"Catalog models:           {summary['model_count']} ({by_prov['pinned_sha256']} SHA-pinned, {by_prov['unpinned_upstream']} unpinned upstream, {by_prov['not_acquired']} not acquired)")
        print(f"TSV cross-check passed:   {summary['tsv_cross_checked']}")
        print(f"Inspection root:          {report['app_home']}")
        for m in report["models"]:
            print(
                f"  - {m['model_id']:28} | prov={m['provenance_status']:17} | local={m['integrity']:14} | terms={m['commercial_status']} | certified={m['quality_certified']}"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
