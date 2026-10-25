#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"

usage() {
  cat <<'EOF'
Usage:
  scripts/macos-benchmark.sh [INPUT_IMAGE] [OUTPUT_DIR] [MODELS...]

Profiles Fidelis restoration candidate models on macOS Apple Silicon (Metal/Vulkan):
- Measures wall-clock latency (ms) and throughput (Megapixels/sec)
- Measures peak resident memory consumption (RSS RAM in MB)
- Evaluates photographic fidelity metrics (SSIM, PSNR, Background Noise)
- Enforces Fidelis Rule #1 geometric & identity drift detection
- Outputs machine-readable macos_benchmark.json and self-contained report.html
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

INPUT="${1:-$repo_root/experiments/eval_crops/portrait_skin_real.png}"
OUTPUT_DIR="${2:-$repo_root/experiments/eval_crops/macos_benchmark}"
shift 2 2>/dev/null || shift 1 2>/dev/null || true
MODELS=("$@")

if [[ ! -f "$INPUT" ]]; then
  if [[ -f "$repo_root/tests/fixtures/portrait_skin.png" ]]; then
    INPUT="$repo_root/tests/fixtures/portrait_skin.png"
  else
    printf 'error: input image not found: %s\n' "$INPUT" >&2
    exit 1
  fi
fi

mkdir -p "$OUTPUT_DIR"

python_bin="${PYTHON_BIN:-}"
if [[ -z "$python_bin" ]]; then
  if [[ -x "$repo_root/.venv/bin/python" ]]; then
    python_bin="$repo_root/.venv/bin/python"
  elif python3 -c "import PIL" >/dev/null 2>&1; then
    python_bin="python3"
  else
    python_bin="python3"
  fi
fi

# Detect macOS hardware details
chip_model="$(sysctl -n machdep.cpu.brand_string 2>/dev/null || echo "Apple Silicon")"
cpu_cores="$(sysctl -n hw.ncpu 2>/dev/null || echo "8")"
mem_bytes="$(sysctl -n hw.memsize 2>/dev/null || echo "17179869184")"
mem_gb="$("$python_bin" -c "print(round($mem_bytes / (1024**3), 1))")"
macos_ver="$(sw_vers -productVersion 2>/dev/null || echo "macOS")"
gpu_info="$(system_profiler SPDisplaysDataType 2>/dev/null | grep "Chipset Model" | head -n1 | sed -E 's/.*Chipset Model: //g' || echo "$chip_model")"
[[ -z "$gpu_info" ]] && gpu_info="$chip_model"

# Resolve models
if [[ ${#MODELS[@]} -eq 0 ]]; then
  available="$("$repo_root/bin/fidelis" models 2>/dev/null || true)"
  if [[ -n "$available" ]]; then
    while IFS= read -r m; do
      [[ -n "$m" ]] && MODELS+=("$m")
    done <<< "$available"
  fi
fi
if [[ ${#MODELS[@]} -eq 0 ]]; then
  MODELS=("RealeSR-general-v3" "ESRGAN-Nomos8kSC")
fi

# Read input dimensions
dim_info="$("$python_bin" - "$INPUT" <<'PY'
from PIL import Image
import sys
im = Image.open(sys.argv[1])
w, h = im.size
print(f"{w} {h} {round((w * 4 * h * 4) / 1000000, 2)}")
PY
)"
src_w="$(echo "$dim_info" | awk '{print $1}')"
src_h="$(echo "$dim_info" | awk '{print $2}')"
out_mp="$(echo "$dim_info" | awk '{print $3}')"

printf "\n========================================================================================\n"
printf " Fidelis Apple Silicon Metal / Vulkan Benchmark\n"
printf " Host: %s (%s cores) | %s GB RAM | macOS %s | GPU: %s\n" "$chip_model" "$cpu_cores" "$mem_gb" "$macos_ver" "$gpu_info"
printf " Source: %s (%sx%s -> %sx%s, %s MP)\n" "$(basename "$INPUT")" "$src_w" "$src_h" "$((src_w*4))" "$((src_h*4))" "$out_mp"
printf "========================================================================================\n"
printf "%-22s %-11s %-12s %-10s %-11s %-8s %-16s\n" "Model" "Latency" "Throughput" "Peak RAM" "Coherence" "SSIM" "Status"
printf '%s\n' "----------------------------------------------------------------------------------------"

benchmark_manifest="$OUTPUT_DIR/macos_benchmark.json"
results_tmp="$OUTPUT_DIR/.results_tmp.json"
rm -f "$results_tmp"
echo "{" > "$results_tmp"

first=true
for model in "${MODELS[@]}"; do
  out_png="$OUTPUT_DIR/${model}.png"
  time_log="$OUTPUT_DIR/.time_${model}.log"

  # Measure execution using /usr/bin/time -l
  t_start="$("$python_bin" -c 'import time; print(time.time())')"
  set +e
  /usr/bin/time -l "$repo_root/bin/fidelis" upscale "$INPUT" "$out_png" --model "$model" > "$time_log" 2>&1
  rc=$?
  set -e
  t_end="$("$python_bin" -c 'import time; print(time.time())')"

  if [[ $rc -ne 0 || ! -s "$out_png" ]]; then
    printf "%-22s %-11s %-12s %-10s %-11s %-8s %-16s\n" "$model" "FAILED" "-" "-" "-" "-" "ERROR"
    continue
  fi

  # Parse elapsed time and peak RSS (in bytes on macOS)
  elapsed_ms="$("$python_bin" -c "print(int(($t_end - $t_start) * 1000))")"
  throughput_mps="$("$python_bin" -c "print(round(($out_mp / max($t_end - $t_start, 0.001)), 2))")"
  peak_bytes="$(grep -i "maximum resident set size" "$time_log" 2>/dev/null | awk '{print $1}' || echo "0")"
  peak_mb="$("$python_bin" -c "print(round(${peak_bytes:-0} / (1024**2), 1))")"
  rm -f "$time_log"

  # Compute drift and fidelity metrics
  drift_eval="$("$python_bin" "$repo_root/scripts/detect-drift.py" "$INPUT" -o "$out_png" 2>/dev/null || echo "{}")"
  coherence="$(echo "$drift_eval" | jq -r '.gradient_coherence_pct // 0')"
  status="$(echo "$drift_eval" | jq -r '.status // "UNKNOWN"')"

  metrics_eval="$("$python_bin" - "$INPUT" "$out_png" "$repo_root" <<'PY'
import sys, json
from PIL import Image
from pathlib import Path
repo = Path(sys.argv[3])
sys.path.insert(0, str(repo / "scripts"))
import importlib.util
spec = importlib.util.spec_from_file_location("eval_metrics", str(repo / "scripts/evaluate-fidelity-metrics.py"))
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
with Image.open(sys.argv[1]) as s, Image.open(sys.argv[2]) as o:
    print(json.dumps(mod.evaluate_pair(s, o)))
PY
  )"
  ssim="$(echo "$metrics_eval" | jq -r '.ssim // 0')"
  psnr="$(echo "$metrics_eval" | jq -r '.psnr_db // 0')"
  bg_noise="$(echo "$metrics_eval" | jq -r '.bg_noise_restraint // 0')"

  printf "%-22s %-11s %-12s %-10s %-11s %-8s %-16s\n" "$model" "${elapsed_ms} ms" "${throughput_mps} MP/s" "${peak_mb} MB" "${coherence}%" "$ssim" "$status"

  # Append to JSON
  [[ "$first" == false ]] && echo "," >> "$results_tmp"
  first=false
  cat >> "$results_tmp" <<JSON
  "$model": {
    "latency_ms": $elapsed_ms,
    "throughput_mp_s": $throughput_mps,
    "peak_rss_mb": $peak_mb,
    "ssim": $ssim,
    "psnr_db": $psnr,
    "bg_noise_restraint": $bg_noise,
    "gradient_coherence_pct": $coherence,
    "rule1_status": "$status",
    "output_file": "$(basename "$out_png")"
  }
JSON
done
echo "}" >> "$results_tmp"

# Compile final macos_benchmark.json
"$python_bin" - "$results_tmp" "$benchmark_manifest" "$INPUT" "$chip_model" "$cpu_cores" "$mem_gb" "$gpu_info" "$macos_ver" <<'PY'
import sys, json, time, pathlib

tmp_res, out_path, inp, chip, cores, ram, gpu, os_ver = sys.argv[1:9]
results = json.loads(pathlib.Path(tmp_res).read_text())

manifest = {
    "timestamp_unix": int(time.time()),
    "environment": {
        "platform": "macOS",
        "chip": chip,
        "cpu_cores": int(cores),
        "total_ram_gb": float(ram),
        "gpu": gpu,
        "os_version": os_ver
    },
    "input": {
        "path": inp,
        "filename": pathlib.Path(inp).name
    },
    "results": results
}
pathlib.Path(out_path).write_text(json.dumps(manifest, indent=2) + "\n")
PY
rm -f "$results_tmp"

printf '%s\n' "----------------------------------------------------------------------------------------"
printf 'Benchmark evidence recorded: %s\n' "$benchmark_manifest"

# Generate visual report if generate-audition-report.py is available
report_py="$repo_root/scripts/generate-audition-report.py"
if [[ -f "$report_py" ]]; then
  "$python_bin" "$report_py" "$OUTPUT_DIR" >/dev/null 2>&1 || true
  if [[ -f "$OUTPUT_DIR/report.html" ]]; then
    printf 'Visual inspection report:   %s\n' "$OUTPUT_DIR/report.html"
  fi
fi
printf '\n'
