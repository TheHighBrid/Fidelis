#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"

usage() {
  cat <<'EOF'
Usage:
  scripts/adb-device-benchmark.sh INPUT_IMAGE [LOCAL_OUTPUT_DIR] [MODELS...]

Automates the Fidelis photo-model candidate benchmark on an Android/Termux device via ADB:
1. Verifies ADB connection and device architecture (ARM64).
2. Pushes the input image to the device.
3. Runs benchmark-photo-candidates.sh inside Termux.
4. Pulls the generated outputs and benchmark.json to LOCAL_OUTPUT_DIR.
5. Generates a standalone HTML visual audition report on your host machine.

Environment variables:
  ANDROID_SERIAL   Specific device serial if multiple devices are connected.
  TERMUX_PREFIX    Path to Termux usr (default: /data/data/com.termux/files/usr)
  TERMUX_HOME      Path to Termux home (default: /data/data/com.termux/files/home)
EOF
}

if [[ $# -lt 1 || "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

INPUT="$1"
LOCAL_OUTPUT_DIR="${2:-./benchmark-device-results}"
shift 2 2>/dev/null || shift 1 2>/dev/null || true
MODELS=("$@")

command -v adb >/dev/null 2>&1 || {
  printf 'error: adb command not found. Please install Android platform-tools or add adb to PATH.\n' >&2
  exit 1
}

[[ -f "$INPUT" ]] || {
  printf 'error: input image not found: %s\n' "$INPUT" >&2
  exit 1
}

ADB_CMD=(adb)
if [[ -n "${ANDROID_SERIAL:-}" ]]; then
  ADB_CMD+=( -s "$ANDROID_SERIAL" )
fi

printf 'Checking ADB device connectivity...\n'
DEVICE_STATE="$("${ADB_CMD[@]}" get-state 2>/dev/null || true)"
if [[ "$DEVICE_STATE" != "device" ]]; then
  printf 'error: no authorized ADB device found. State: %s\n' "${DEVICE_STATE:-none}" >&2
  printf 'Ensure USB debugging is enabled and authorized on your device.\n' >&2
  "${ADB_CMD[@]}" devices -l >&2
  exit 1
fi

DEVICE_MODEL="$("${ADB_CMD[@]}" shell getprop ro.product.model | tr -d '\r')"
DEVICE_ABI="$("${ADB_CMD[@]}" shell getprop ro.product.cpu.abi | tr -d '\r')"
DEVICE_SOC="$("${ADB_CMD[@]}" shell getprop ro.soc.model 2>/dev/null | tr -d '\r')"
printf 'Connected device: %s (ABI: %s, SoC: %s)\n' "$DEVICE_MODEL" "$DEVICE_ABI" "${DEVICE_SOC:-unknown}"

if [[ "$DEVICE_ABI" != "arm64-v8a" && "$DEVICE_ABI" != "aarch64" ]]; then
  printf 'warning: device ABI is %s (expected arm64-v8a/aarch64).\n' "$DEVICE_ABI" >&2
fi

TERMUX_HOME="${TERMUX_HOME:-/data/data/com.termux/files/home}"
TERMUX_PREFIX="${TERMUX_PREFIX:-/data/data/com.termux/files/usr}"
REMOTE_WORK="$TERMUX_HOME/fidelis-device-benchmark"
REMOTE_IN="$REMOTE_WORK/input"
REMOTE_OUT="$REMOTE_WORK/results"

printf 'Setting up remote benchmark directory in Termux (%s)...\n' "$REMOTE_WORK"
"${ADB_CMD[@]}" shell "mkdir -p '$REMOTE_IN' '$REMOTE_OUT'"

INPUT_FILENAME="$(basename "$INPUT")"
REMOTE_IMAGE="$REMOTE_IN/$INPUT_FILENAME"

printf 'Pushing %s to device...\n' "$INPUT_FILENAME"
"${ADB_CMD[@]}" push "$INPUT" "$REMOTE_IMAGE"

SYNC_DIR="$REMOTE_WORK/fidelis-sync"
printf 'Syncing Fidelis scripts and config to device...\n'
"${ADB_CMD[@]}" shell "mkdir -p '$SYNC_DIR/bin' '$SYNC_DIR/config' '$SYNC_DIR/scripts' '$SYNC_DIR/docs'"
"${ADB_CMD[@]}" push "$repo_root/bin/fidelis" "$SYNC_DIR/bin/"
"${ADB_CMD[@]}" push "$repo_root/config/photo-candidates.tsv" "$SYNC_DIR/config/"
"${ADB_CMD[@]}" push "$repo_root/scripts/benchmark-photo-candidates.sh" "$SYNC_DIR/scripts/"
"${ADB_CMD[@]}" push "$repo_root/scripts/install-photo-candidate.sh" "$SYNC_DIR/scripts/"
"${ADB_CMD[@]}" push "$repo_root/scripts/detect-vulkan.sh" "$SYNC_DIR/scripts/"
"${ADB_CMD[@]}" shell "chmod +x '$SYNC_DIR/bin/fidelis' '$SYNC_DIR/scripts/'*.sh"

printf '\nRunning photo candidate benchmark on device...\n'
MODEL_ARGS=""
if [[ ${#MODELS[@]} -gt 0 ]]; then
  MODEL_ARGS="${MODELS[*]}"
fi

TERMUX_EXEC_CMD="
export PATH=\"$SYNC_DIR/bin:$TERMUX_PREFIX/bin:\$PATH\"
export PREFIX=\"$TERMUX_PREFIX\"
export HOME=\"$TERMUX_HOME\"
export LD_LIBRARY_PATH=\"$TERMUX_PREFIX/lib:\$LD_LIBRARY_PATH\"
bash '$SYNC_DIR/scripts/benchmark-photo-candidates.sh' '$REMOTE_IMAGE' '$REMOTE_OUT' $MODEL_ARGS
"

"${ADB_CMD[@]}" shell "$TERMUX_EXEC_CMD"

mkdir -p "$LOCAL_OUTPUT_DIR"
printf '\nPulling benchmark results back to %s...\n' "$LOCAL_OUTPUT_DIR"
"${ADB_CMD[@]}" pull "$REMOTE_OUT/." "$LOCAL_OUTPUT_DIR/"

if [[ -f "$LOCAL_OUTPUT_DIR/benchmark.json" ]]; then
  printf '\nBenchmark evidence successfully retrieved: %s/benchmark.json\n' "$LOCAL_OUTPUT_DIR"
  REPORT_SCRIPT="$repo_root/scripts/generate-audition-report.py"
  if [[ -f "$REPORT_SCRIPT" ]]; then
    printf 'Generating visual inspection report...\n'
    python3 "$REPORT_SCRIPT" "$LOCAL_OUTPUT_DIR" -o "$LOCAL_OUTPUT_DIR/report.html" 2>/dev/null || true
  fi
  printf 'Ready for review: %s/report.html\n' "$LOCAL_OUTPUT_DIR"
else
  printf 'warning: benchmark.json was not found in retrieved results.\n' >&2
fi
