#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
if [[ $# -ne 2 || ! "$1" =~ ^[0-9a-f]{40}$ ]]; then
  printf 'Usage: %s <full-source-commit-sha> <new-output-directory>\n' "$0" >&2
  exit 2
fi
source_sha="$(git -C "$repo_root" rev-parse --verify "$1^{commit}")"
[[ "$source_sha" == "$1" ]] || exit 2
output_dir="$2"
stage="$(mktemp -d "${TMPDIR:-/tmp}/fidelis-preview.XXXXXX")"
trap 'rm -rf "$stage"' EXIT
git -C "$repo_root" archive "$source_sha" | tar -xf - -C "$stage"

python_bin="$repo_root/.venv/bin/python"
if [[ ! -x "$python_bin" ]]; then
  python_bin="$(command -v python3)"
fi

"$python_bin" - "$stage" "$source_sha" "$output_dir" <<'PY'
import json
from pathlib import Path
import platform
import sys
import zlib

stage, source_sha, output_dir = sys.argv[1:]
sys.path.insert(0, stage)
from fidelis.studio.packaging import (
    audit_release_archive,
    create_deterministic_tar_gz,
    create_deterministic_zip,
    is_excluded_release_path,
)

def exclude_preview_path(path):
    return (
        is_excluded_release_path(path)
        or path == "experiments/eval_crops"
        or path.startswith("experiments/eval_crops/")
    )

output = Path(output_dir).resolve()
output.mkdir()
name = f"fidelis-local-preview-{source_sha[:12]}"
packages = []
for extension, build in (
    ("tar.gz", create_deterministic_tar_gz),
    ("zip", create_deterministic_zip),
):
    archive = output / f"{name}.{extension}"
    checksum = build(stage, archive, exclude_fn=exclude_preview_path)
    result = audit_release_archive(archive)
    if not result["passed"] or result["archive_sha256"] != checksum:
        raise SystemExit(f"Archive verification failed: {result}")
    packages.append({"path": archive.name, "sha256": checksum})

receipt = {
    "schema_version": "fidelis.local_preview.v1",
    "source_commit": source_sha,
    "builder": {
        "python": platform.python_version(),
        "zlib": zlib.ZLIB_RUNTIME_VERSION,
        "platform": platform.platform(),
    },
    "bundled_models": [],
    "packages": packages,
}
(output / "preview-receipt.json").write_text(
    json.dumps(receipt, indent=2) + "\n", encoding="utf-8"
)
print(output / "preview-receipt.json")
PY
