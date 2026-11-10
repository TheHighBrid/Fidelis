#!/usr/bin/env python3
"""Audit release archives and manage workspace upgrade/rollback snapshots (F15 / MEL-69)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from fidelis.studio.packaging import (  # noqa: E402
    audit_release_archive,
    create_workspace_snapshot,
    restore_workspace_snapshot,
    verify_workspace_integrity,
)


def _write_or_print(report: dict, output_path: str | None) -> None:
    text = json.dumps(report, indent=2) + "\n"
    if output_path:
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Audit Fidelis release packages and protect saved workspaces on upgrade/rollback."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_audit = sub.add_parser("audit-archive", help="Verify archive contents and exclusions.")
    p_audit.add_argument("archive", help="Path to .tar.gz or .zip archive")
    p_audit.add_argument(
        "--strip-top-level",
        action="store_true",
        help="Strip a single top-level bundle directory prefix (e.g. offline bundle).",
    )
    p_audit.add_argument("--output", help="Optional JSON output path")

    p_verify = sub.add_parser("verify-workspace", help="Verify JobStore and GenerationRunStore state.")
    p_verify.add_argument("--region-root", required=True, help="Path to region_jobs directory")
    p_verify.add_argument("--generation-root", help="Optional path to generation_runs directory")
    p_verify.add_argument("--output", help="Optional JSON output path")

    p_snap = sub.add_parser("snapshot", help="Create a verified pre-upgrade workspace snapshot.")
    p_snap.add_argument("--region-root", required=True, help="Path to region_jobs directory")
    p_snap.add_argument("--generation-root", help="Optional path to generation_runs directory")
    p_snap.add_argument("--snapshot-dir", required=True, help="Destination snapshot directory")
    p_snap.add_argument("--target-version", default="unknown", help="Target version label")
    p_snap.add_argument("--output", help="Optional JSON output path")

    p_restore = sub.add_parser("restore", help="Atomically restore workspace from a verified snapshot.")
    p_restore.add_argument("--snapshot-dir", required=True, help="Source snapshot directory")
    p_restore.add_argument("--region-root", required=True, help="Destination region_jobs directory")
    p_restore.add_argument("--generation-root", help="Optional destination generation_runs directory")
    p_restore.add_argument("--output", help="Optional JSON output path")

    args = parser.parse_args(argv)

    if args.command == "audit-archive":
        report = audit_release_archive(
            args.archive, strip_top_level=bool(args.strip_top_level)
        )
        _write_or_print(report, args.output)
        return 0 if report["passed"] else 2

    if args.command == "verify-workspace":
        report = verify_workspace_integrity(args.region_root, args.generation_root)
        _write_or_print(report, args.output)
        return 0 if report["passed"] else 2

    if args.command == "snapshot":
        report = create_workspace_snapshot(
            args.region_root,
            args.snapshot_dir,
            generation_root=args.generation_root,
            target_version=args.target_version,
        )
        _write_or_print(report, args.output)
        return 0

    if args.command == "restore":
        report = restore_workspace_snapshot(
            args.snapshot_dir,
            args.region_root,
            generation_root=args.generation_root,
        )
        _write_or_print(report, args.output)
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
