#!/usr/bin/env python3
"""Audit evidence-backed production release readiness (F16 / MEL-68)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from fidelis.studio.release_readiness import evaluate_release_readiness  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate production release readiness against F16 / QUALITY_GATES.md."
    )
    parser.add_argument(
        "--backlog",
        type=Path,
        default=REPO_ROOT / "docs" / "project" / "backlog.json",
        help="Path to docs/project/backlog.json",
    )
    parser.add_argument(
        "--release-manifest",
        type=Path,
        help="Optional release candidate manifest JSON with packages, quality report, rollback, and signoff",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional path to write evaluated release readiness dossier JSON",
    )
    parser.add_argument(
        "--allow-blocked",
        action="store_true",
        help="Exit 0 after writing/printing the dossier even when release gates are still blocked",
    )
    args = parser.parse_args(argv)

    backlog_data = json.loads(args.backlog.read_text(encoding="utf-8"))
    manifest_data = (
        json.loads(args.release_manifest.read_text(encoding="utf-8"))
        if args.release_manifest and args.release_manifest.is_file()
        else None
    )

    dossier = evaluate_release_readiness(
        backlog_data,
        release_manifest=manifest_data,
        repo_root=REPO_ROOT,
    )

    text = json.dumps(dossier, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)

    if dossier["ready_for_release"] or args.allow_blocked:
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
