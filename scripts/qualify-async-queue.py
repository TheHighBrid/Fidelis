#!/usr/bin/env python3
"""Qualify F07 durable async Studio jobs, scoped cancellation, and restart recovery.

Exercises `scripts/web-ui.py` over loopback HTTP (`127.0.0.1`) backed by
`GenerationQueue` and `ComfyTextureBackend` in either `--fixture` mode (E1) or
live ComfyUI worker mode (E2). Never records E3 or E4 acceptance.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from fidelis.studio.async_qualification import (  # noqa: E402
    DEFAULT_COMFY_ADDRESS,
    SCHEMA_VERSION,
    run_qualification,
)

__all__ = ["DEFAULT_COMFY_ADDRESS", "SCHEMA_VERSION", "main", "run_qualification"]


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint for F07 async Studio queue qualification."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", action="store_true", help="Run against embedded mock ComfyUI fixture (E1)")
    parser.add_argument("--address", default=DEFAULT_COMFY_ADDRESS, help="Loopback ComfyUI endpoint")
    parser.add_argument("--workflow", type=Path, help="Optional ComfyUI API workflow bundle JSON")
    parser.add_argument("--source", type=Path, help="Optional source image path")
    parser.add_argument("--max-edge", type=int, default=256, help="Max edge when scaling source image")
    parser.add_argument("--deadline", type=float, default=120.0, help="Per-task polling deadline in seconds")
    parser.add_argument("--evidence-dir", type=Path, help="Optional off-repo directory to retain workspaces")
    parser.add_argument("--output", type=Path, help="Optional path to write JSON receipt")
    args = parser.parse_args(argv)

    receipt = run_qualification(
        fixture=args.fixture,
        address=args.address,
        workflow_path=args.workflow,
        source_path=args.source,
        evidence_dir=args.evidence_dir,
        output_path=args.output,
        max_edge=args.max_edge,
        deadline_seconds=args.deadline,
    )
    sys.stdout.write(json.dumps(receipt, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
