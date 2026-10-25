#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"

usage() {
  cat <<'EOF'
Usage:
  scripts/batch-audition.sh INPUT_DIR OUTPUT_DIR [MODELS...]

Auditions an entire directory of photos against candidate models, computes objective
fidelity metrics for each photo, and generates an aggregate Master Lookbook HTML Portfolio.

Examples:
  fidelis batch-audition ./photoshoot ./results
  fidelis batch-audition ./editorial ./lookbook RealeSR-general-v3 ESRGAN-Remacri
EOF
}

if [[ $# -lt 2 || "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

INPUT_DIR="$1"
OUTPUT_DIR="$2"
shift 2 || true
MODELS=("$@")

[[ -d "$INPUT_DIR" ]] || {
  printf 'error: input directory not found: %s\n' "$INPUT_DIR" >&2
  exit 1
}

mkdir -p "$OUTPUT_DIR"
AUDITIONS_ROOT="$OUTPUT_DIR/auditions"
mkdir -p "$AUDITIONS_ROOT"

cli="${FIDELIS_CLI:-$repo_root/bin/fidelis}"

# Find image files
images=()
while IFS= read -r -d '' f; do
  images+=("$f")
done < <(find "$INPUT_DIR" -maxdepth 1 -type f \( -iname "*.png" -o -iname "*.jpg" -o -iname "*.jpeg" -o -iname "*.webp" \) -print0 | sort -z)

[[ ${#images[@]} -gt 0 ]] || {
  printf 'error: no images found in directory: %s\n' "$INPUT_DIR" >&2
  exit 1
}

printf '\nFound %d photograph(s) in %s to audition.\n' "${#images[@]}" "$INPUT_DIR"

idx=0
for img in "${images[@]}"; do
  idx=$(( idx + 1 ))
  stem="$(basename "$img")"
  stem="${stem%.*}"
  target_aud="$AUDITIONS_ROOT/audition_$stem"
  
  printf '\n[%d/%d] Auditioning %s -> %s\n' "$idx" "${#images[@]}" "$(basename "$img")" "$target_aud"
  if [[ ${#MODELS[@]} -gt 0 ]]; then
    "$cli" audition "$img" "$target_aud" "${MODELS[@]}"
  else
    "$cli" audition "$img" "$target_aud"
  fi

  # Compute objective metrics
  "$cli" evaluate "$target_aud" >/dev/null 2>&1 || true
done

printf '\nGenerating Master Lookbook HTML Portfolio...\n'
py="$("$cli" resolve-python 2>/dev/null || echo python3)"
if [[ ! -x "$py" ]]; then
  py="${repo_root}/.venv/bin/python"
  [[ -x "$py" ]] || py="python3"
fi

LOOKBOOK_HTML="$OUTPUT_DIR/lookbook.html"
"$py" "$repo_root/scripts/generate-master-dashboard.py" "$AUDITIONS_ROOT" \
  -o "$LOOKBOOK_HTML" \
  --title "Fidelis Editorial Lookbook Audition"

printf '\nLookbook complete: %s\n' "$LOOKBOOK_HTML"
printf 'Portfolio contains %d photograph(s) audited across all candidate models.\n' "${#images[@]}"
