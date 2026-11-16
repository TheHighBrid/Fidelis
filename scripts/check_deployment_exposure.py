#!/usr/bin/env python3
"""Fail-closed audit of Compose port publication for Fidelis's local-only UI.

This intentionally recognizes only a small, documented subset of Compose ports.
Unknown syntax is rejected rather than assumed private. No PyYAML dependency.
"""
from __future__ import annotations

import argparse
import pathlib
import re
import sys

LOOPBACK = {"127.0.0.1", "::1", "[::1]"}
PORT = re.compile(r"^(?:(?P<host>\[[^]]+\]|[^:]+):)?(?P<published>\d+):(?P<target>\d+)(?:/(?:tcp|udp))?$")


def check_compose(text: str) -> list[str]:
    errors: list[str] = []
    in_ports = False
    indent = -1
    seen_ports = False
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.split(" #", 1)[0].rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        depth = len(line) - len(line.lstrip())
        stripped = line.strip()
        if in_ports and depth <= indent:
            in_ports = False
        if stripped == "ports:":
            in_ports, indent, seen_ports = True, depth, True
            continue
        if not in_ports:
            continue
        if not stripped.startswith("- "):
            errors.append(f"line {number}: unsupported port mapping syntax")
            continue
        value = stripped[2:].strip().strip("'\"")
        match = PORT.fullmatch(value)
        if not match:
            errors.append(f"line {number}: unsupported or ambiguous port mapping {value!r}")
        elif match.group("host") not in LOOPBACK:
            errors.append(f"line {number}: port {value!r} is not explicitly loopback-bound")
    if not seen_ports:
        errors.append("no Compose ports section found; unable to verify publication policy")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("compose", type=pathlib.Path, nargs="?", default=pathlib.Path("docker-compose.yml"))
    args = parser.parse_args()
    try:
        problems = check_compose(args.compose.read_text(encoding="utf-8"))
    except OSError as exc:
        print(f"FAIL: cannot inspect Compose file: {exc}", file=sys.stderr)
        return 2
    for problem in problems:
        print(f"FAIL: {problem}", file=sys.stderr)
    if problems:
        return 1
    print("PASS: all recognized published ports explicitly bind to loopback")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
