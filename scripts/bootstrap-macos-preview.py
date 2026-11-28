"""Stage verified native runtime archives and the cleared model into a new home."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fidelis.studio.native_preview import bootstrap_native_preview


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-dir", required=True, type=Path)
    parser.add_argument("--model-cache", required=True, type=Path,
                        help="Prepared runtime-style model cache; weights and terms are checked")
    parser.add_argument("--runtime-home", required=True, type=Path,
                        help="New nonexistent home; no existing installation is replaced")
    args = parser.parse_args()
    try:
        receipt = bootstrap_native_preview(ROOT, archive_dir=args.archive_dir,
                                           model_cache=args.model_cache, app_home=args.runtime_home)
    except (OSError, ValueError, RuntimeError) as error:
        parser.exit(2, f"native preview bootstrap: {error}\n")
    print(json.dumps(receipt, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
