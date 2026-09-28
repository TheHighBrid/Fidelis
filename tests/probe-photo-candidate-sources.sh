#!/usr/bin/env bash
set -Eeuo pipefail

work="$(mktemp -d "${TMPDIR:-/tmp}/fidelis-candidate-probe.XXXXXX")"
trap 'rm -rf "$work"' EXIT

fetch_candidate() {
  local name="$1" revision="$2" folder="$3" expected_bin_sha="$4"
  local base="https://huggingface.co/tumuyan2/realsr-models/resolve/$revision/$folder"
  local dest="$work/$name"
  mkdir -p "$dest"

  curl -fsSL --retry 3 --retry-delay 2 "$base/x4.param?download=true" -o "$dest/x4.param"
  curl -fsSL --retry 3 --retry-delay 2 "$base/x4.bin?download=true" -o "$dest/x4.bin"

  [[ -s "$dest/x4.param" && -s "$dest/x4.bin" ]]
  actual_bin_sha="$(sha256sum "$dest/x4.bin" | awk '{print $1}')"
  [[ "$actual_bin_sha" == "$expected_bin_sha" ]] || {
    printf 'Binary hash mismatch for %s\nexpected=%s\nactual=%s\n' "$name" "$expected_bin_sha" "$actual_bin_sha" >&2
    return 1
  }

  printf 'CANDIDATE %s\n' "$name"
  printf 'param_sha256=%s\n' "$(sha256sum "$dest/x4.param" | awk '{print $1}')"
  printf 'bin_sha256=%s\n' "$actual_bin_sha"
  printf 'param_bytes=%s\n' "$(wc -c < "$dest/x4.param" | tr -d '[:space:]')"
  printf 'bin_bytes=%s\n' "$(wc -c < "$dest/x4.bin" | tr -d '[:space:]')"
}

fetch_candidate \
  RealeSR-general-v3 \
  0fe68041370150c7695816e229dc982bfc06ed58 \
  models-RealeSR-general-v3 \
  01450f4a79b81c0f1f3eeefc31121167886125c25e41a6d4773e8ec8062528a1

fetch_candidate \
  RealSR-DF2K \
  a7b0161ee1b8c70843b3facce834cdac63118c41 \
  models-DF2K \
  a3f5eb53906ef54d5c5d125b2c9dd5f570d9dbb779e3d934df14b5375fd923c1

fetch_candidate \
  ESRGAN-Remacri \
  489b523a30aabfb98002b20797ff55fcef6cb1bd \
  models-ESRGAN-Remacri \
  a43be595c0d743314c30b50fe7ef188be0c61cc55c46ce81adb79ba4b3c3fb7a
