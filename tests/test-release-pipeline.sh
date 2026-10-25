#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
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

# Clean up test distribution files
rm -f "$repo_root"/dist/*"${test_ver}"*

printf '\nRelease pipeline and offline bundle verification tests passed.\n'
