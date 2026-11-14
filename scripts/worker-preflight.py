#!/usr/bin/env python3
"""Run a reproducible, secret-safe live-worker and workflow schema preflight (F05-A / MEL-76)."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from fidelis.studio.worker_preflight import DEFAULT_POLICY_PATH, run_worker_preflight


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--address", default="http://127.0.0.1:8188", help="Loopback or SSH-tunneled ComfyUI HTTP endpoint")
    parser.add_argument("--workflow", type=Path, help="Optional exported ComfyUI workflow bundle JSON")
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY_PATH, help="Worker preflight policy JSON")
    parser.add_argument("--app-home", type=Path, help="Optional FIDELIS_HOME runtime directory")
    parser.add_argument("--timeout", type=float, default=2.0, help="HTTP probe timeout in seconds")
    parser.add_argument("--owner", default="local-operator", help="Explicit resource owner role or handle")
    parser.add_argument(
        "--access-method",
        choices=("loopback", "ssh_tunnel"),
        default="loopback",
        help="Explicit local worker connection method",
    )
    parser.add_argument("--output", type=Path, help="Optional path to write the JSON preflight receipt")
    parser.add_argument("--require-reachable", action="store_true", help="Exit non-zero if the worker endpoint is unreachable")
    parser.add_argument(
        "--require-qualified",
        action="store_true",
        help="Exit non-zero unless preflight_status is qualified_preflight",
    )
    args = parser.parse_args(argv)

    receipt = run_worker_preflight(
        REPO_ROOT,
        address=args.address,
        workflow_path=args.workflow,
        policy_path=args.policy,
        app_home=args.app_home,
        timeout=args.timeout,
        owner=args.owner,
        access_method=args.access_method,
    )

    rendered = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    sys.stdout.write(rendered)

    if receipt["preflight_status"] == "policy_violation":
        return 2
    if args.require_qualified and receipt["preflight_status"] != "qualified_preflight":
        return 1
    if args.require_reachable and not receipt["worker"]["reachable"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
