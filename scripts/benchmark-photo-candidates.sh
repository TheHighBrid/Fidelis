#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
cli="${FIDELIS_CLI:-fidelis}"
installer="${FIDELIS_CANDIDATE_INSTALLER:-$repo_root/scripts/install-photo-candidate.sh}"
app_home="${FIDELIS_HOME:-$HOME/.local/share/fidelis}"
engine="$app_home/runtime/realsr-ncnn"

usage() {
  cat <<'EOF'
Usage:
  scripts/benchmark-photo-candidates.sh INPUT OUTPUT_DIR [MODEL ...]

If no models are supplied, Fidelis benchmarks its first mobile candidate against
the installed Nomos baseline:
  RealeSR-general-v3 ESRGAN-Nomos8kSC

Missing curated candidates are installed through the checksum-locked candidate
installer before inference. Outputs remain standalone PNG files, one per model.
EOF
}

[[ $# -ge 2 ]] || { usage >&2; exit 2; }
input="$(realpath "$1")"
output_dir="$(realpath -m "$2")"
shift 2
[[ -f "$input" ]] || { printf 'Benchmark input must be one image file: %s\n' "$input" >&2; exit 1; }

models=("$@")
if [[ ${#models[@]} -eq 0 ]]; then
  models=(RealeSR-general-v3 ESRGAN-Nomos8kSC)
fi

command -v jq >/dev/null 2>&1 || { printf 'jq is required.\n' >&2; exit 1; }
command -v sha256sum >/dev/null 2>&1 || { printf 'sha256sum is required.\n' >&2; exit 1; }
[[ -x "$engine" ]] || { printf 'Fidelis runtime is not installed: %s\n' "$engine" >&2; exit 1; }

mkdir -p "$output_dir"
rm -f "$output_dir/benchmark.json"
entries="$output_dir/.benchmark-entries.$$"
manifest_tmp="$output_dir/.benchmark.json.new.$$"
: > "$entries"
trap 'rm -f "$entries" "$manifest_tmp"' EXIT

benchmark_started_ns="$(date +%s%N)"
input_sha="$(sha256sum "$input" | awk '{print $1}')"
input_bytes="$(wc -c < "$input" | tr -d '[:space:]')"
engine_sha="$(sha256sum "$engine" | awk '{print $1}')"

for requested in "${models[@]}"; do
  model="${requested#models-}"
  [[ -n "$model" && "$model" =~ ^[A-Za-z0-9._-]+$ ]] || {
    printf 'Invalid model name: %s\n' "$requested" >&2
    exit 2
  }

  if ! provenance="$("$cli" model-info "$model" 2>/dev/null)"; then
    printf 'Installing missing curated candidate: %s\n' "$model"
    bash "$installer" "$model"
    provenance="$("$cli" model-info "$model")"
  fi

  safe="${model//[^A-Za-z0-9._-]/_}"
  output="$output_dir/$safe.png"
  rm -f "$output"

  printf '\n[%s] benchmarking -> %s\n' "$model" "$output"
  start_ns="$(date +%s%N)"
  "$cli" upscale "$input" "$output" --model "$model"
  end_ns="$(date +%s%N)"
  elapsed_ms=$(( (end_ns - start_ns) / 1000000 ))

  [[ -s "$output" ]] || {
    printf 'Benchmark failed: %s produced no non-empty output.\n' "$model" >&2
    rm -f "$output"
    exit 1
  }

  output_sha="$(sha256sum "$output" | awk '{print $1}')"
  output_bytes="$(wc -c < "$output" | tr -d '[:space:]')"

  jq -cn \
    --argjson model "$provenance" \
    --arg filename "$(basename "$output")" \
    --arg sha256 "$output_sha" \
    --argjson bytes "$output_bytes" \
    --argjson elapsed_ms "$elapsed_ms" \
    '{model:$model,runtime:{elapsed_ms:$elapsed_ms},output:{filename:$filename,bytes:$bytes,sha256:$sha256}}' \
    >> "$entries"

done

benchmark_finished_ns="$(date +%s%N)"
total_elapsed_ms=$(( (benchmark_finished_ns - benchmark_started_ns) / 1000000 ))
created_at="$(date -u +'%Y-%m-%dT%H:%M:%SZ')"
architecture="$(uname -m)"
kernel="$(uname -r)"

jq -s \
  --arg created_at "$created_at" \
  --arg input_path "$input" \
  --arg input_sha256 "$input_sha" \
  --argjson input_bytes "$input_bytes" \
  --arg engine_sha256 "$engine_sha" \
  --arg architecture "$architecture" \
  --arg kernel "$kernel" \
  --argjson total_elapsed_ms "$total_elapsed_ms" \
  '{schema_version:1,command:"benchmark-photo-candidates",created_at:$created_at,host:{architecture:$architecture,kernel:$kernel},input:{path:$input_path,bytes:$input_bytes,sha256:$input_sha256},engine:{name:"realsr-ncnn",sha256:$engine_sha256,scale:4,tile:256},runtime:{total_elapsed_ms:$total_elapsed_ms},models:.}' \
  "$entries" > "$manifest_tmp"

mv "$manifest_tmp" "$output_dir/benchmark.json"
rm -f "$entries"
trap - EXIT

printf '\nBenchmark complete: %d model(s).\n' "${#models[@]}"
printf 'Evidence: %s\n' "$output_dir/benchmark.json"
