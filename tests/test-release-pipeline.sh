#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
python_bin="$repo_root/.venv/bin/python"
if [[ ! -x "$python_bin" ]]; then
  python_bin="$(command -v python3)"
fi
work="$(mktemp -d "${TMPDIR:-/tmp}/fidelis-release-test.XXXXXX")"
trap 'rm -rf "$work"' EXIT

test_ver="3.9.9-test"
export VERSION="$test_ver"

printf '1. Testing package-release.sh...\n'
bash "$repo_root/scripts/package-release.sh" "$test_ver"

tar_out="$repo_root/dist/fidelis-v${test_ver}.tar.gz"
zip_out="$repo_root/dist/fidelis-v${test_ver}.zip"

test -s "$tar_out"
test -s "$tar_out.sha256"

# Verify checksum
if command -v sha256sum >/dev/null 2>&1; then
  sha256sum --check "$tar_out.sha256" >/dev/null
else
  shasum -a 256 --check "$tar_out.sha256" >/dev/null
fi

"$python_bin" "$repo_root/scripts/verify-upgrade-rollback.py" audit-archive "$tar_out" >/dev/null
if [[ -f "$zip_out" ]]; then
  "$python_bin" "$repo_root/scripts/verify-upgrade-rollback.py" audit-archive "$zip_out" >/dev/null
fi

printf '2. Testing package-offline-bundle.sh...\n'
bash "$repo_root/scripts/package-offline-bundle.sh" "$test_ver"

bundle_tar="$repo_root/dist/fidelis-offline-bundle-v${test_ver}.tar.gz"
test -s "$bundle_tar"
test -s "$bundle_tar.sha256"

if command -v sha256sum >/dev/null 2>&1; then
  sha256sum --check "$bundle_tar.sha256" >/dev/null
else
  shasum -a 256 --check "$bundle_tar.sha256" >/dev/null
fi

"$python_bin" "$repo_root/scripts/verify-upgrade-rollback.py" audit-archive --strip-top-level "$bundle_tar" >/dev/null

printf '3. Testing isolated unarchive and offline deployment...\n'
extract_dir="$work/extract"
mkdir -p "$extract_dir"
tar -xzf "$bundle_tar" -C "$extract_dir"

test -f "$extract_dir/fidelis-offline-bundle-v${test_ver}/install-offline.sh"
test -d "$extract_dir/fidelis-offline-bundle-v${test_ver}/offline_models"

# Test install-offline.sh in isolated sandbox
sandbox_home="$work/sandbox_home"
export FIDELIS_HOME="$sandbox_home"

(
  cd "$extract_dir/fidelis-offline-bundle-v${test_ver}"
  bash install-offline.sh
)

test -x "$sandbox_home/bin/fidelis"
test -d "$sandbox_home/runtime"

printf '4. Testing commit-pinned local preview packaging...\n'
source_sha="$(git -C "$repo_root" rev-parse HEAD)"
for preview in "$work/preview-a" "$work/preview-b"; do
  bash "$repo_root/scripts/package-local-preview.sh" "$source_sha" "$preview"
done
diff -r "$work/preview-a" "$work/preview-b"
"$python_bin" - "$work/preview-a/preview-receipt.json" "$source_sha" <<'PY'
import hashlib
import json
from pathlib import Path
import sys

receipt_path = Path(sys.argv[1])
receipt = json.loads(receipt_path.read_text())
assert receipt["source_commit"] == sys.argv[2]
assert receipt["bundled_models"] == []
assert len(receipt["packages"]) == 2
for package in receipt["packages"]:
    archive = receipt_path.parent / package["path"]
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == package["sha256"]
PY

# Clean up test distribution files
rm -f "$repo_root"/dist/*"${test_ver}"*

printf '\nRelease pipeline and offline bundle verification tests passed.\n'
