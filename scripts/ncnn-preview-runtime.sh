#!/usr/bin/env bash
set -Eeuo pipefail

runtime_dir="$(cd "$(dirname "$0")" && pwd)"
input="" output="" model="" scale=4 tile=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help)
      printf 'Fidelis preview runtime: RealeSR-general-v3, 4x\n'
      "$runtime_dir/realesrgan-binary" -h 2>&1 || true
      exit 0 ;;
    -i|-o|-m|-s|-t)
      [[ $# -ge 2 ]] || { printf 'Missing option value\n' >&2; exit 2; }
      case "$1" in
        -i) input="$2" ;; -o) output="$2" ;; -m) model="$2" ;;
        -s) scale="$2" ;; -t) tile="$2" ;;
      esac
      shift 2 ;;
    *) printf 'Unsupported preview runtime option: %s\n' "$1" >&2; exit 2 ;;
  esac
done
[[ -n "$input" && -n "$output" && -n "$model" && "$scale" == 4 && "$tile" =~ ^[0-9]+$ ]] || {
  printf 'Expected input/output, RealeSR model, 4x scale and nonnegative tile size\n' >&2
  exit 2
}
[[ "$(basename "$model")" == models-RealeSR-general-v3 && -s "$model/x4.param" && -s "$model/x4.bin" ]] || {
  printf 'This preview runtime supports only the staged RealeSR-general-v3 model\n' >&2
  exit 2
}
model="$(cd "$model" && pwd -P)"
stage_root="$(mktemp -d "${TMPDIR:-/tmp}/fidelis-preview-model.XXXXXX")"
trap 'rm -rf "$stage_root"' EXIT
mkdir "$stage_root/models"
ln -s "$model/x4.param" "$stage_root/models/realesr-animevideov3-x4.param"
ln -s "$model/x4.bin" "$stage_root/models/realesr-animevideov3-x4.bin"
"$runtime_dir/realesrgan-binary" -i "$input" -o "$output" -m "$stage_root/models" \
  -n realesr-animevideov3 -s 4 -t "$tile"
