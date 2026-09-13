#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
bash -n "$repo_root/install.sh"
bash -n "$repo_root/bin/fidelis"
bash -n "$repo_root/scripts/detect-vulkan.sh"

grep -q 'GUI-armv8a' "$repo_root/install.sh"
grep -q 'models-ESRGAN-Nomos8kSC' "$repo_root/install.sh"
grep -q 'checksum mismatch' "$repo_root/install.sh"

printf 'Static smoke tests passed.\n'

