"""Install only hash-locked local wheels into a new preview Python environment."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fidelis.studio.offline_environment import install_offline_environment


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheelhouse", type=Path, required=True)
    parser.add_argument("--requirements-lock", type=Path, required=True)
    parser.add_argument("--app-root", type=Path, default=ROOT,
                        help="Extracted source root; existing .venv or install receipts are refused")
    parser.add_argument("--python", default=sys.executable,
                        help="Existing compatible interpreter with stdlib venv/ensurepip")
    args = parser.parse_args()
    try:
        receipt = install_offline_environment(
            args.app_root, wheelhouse=args.wheelhouse,
            requirements_lock=args.requirements_lock, python_executable=args.python,
        )
    except (OSError, ValueError, RuntimeError) as error:
        parser.exit(2, f"offline Python installation: {error}\n")
    print(json.dumps(receipt, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
