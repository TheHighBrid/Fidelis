#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
cli="$repo_root/bin/fidelis"
test_tmp="$(mktemp -d "${TMPDIR:-/tmp}/fidelis-portrait-test.XXXXXX")"
trap 'rm -rf "$test_tmp"' EXIT

src_fixture="$repo_root/tests/fixtures/portrait_skin.png"
out_img="$test_tmp/restored.png"

# Test fidelis portrait command
"$cli" portrait "$src_fixture" "$out_img" -w 0.70 --direct

[[ -f "$out_img" ]] || {
  printf 'FAIL: Portrait output image not created.\n' >&2
  exit 1
}

printf 'Portrait engine CLI tests passed.\n'
