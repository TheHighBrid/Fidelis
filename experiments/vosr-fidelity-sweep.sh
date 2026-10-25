#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  vosr-fidelity-sweep.sh INPUT_IMAGE [OUTPUT_DIR] [--include-onestep]

Environment overrides:
  VOSR_DIR            Path to cswry/VOSR checkout (default: $HOME/VOSR)
  VOSR_CKPT           Multi-step checkpoint path, absolute or relative to VOSR_DIR
                      (default: preset/ckpts/VOSR_1.4B_ms)
  VOSR_ONESTEP_CKPT   One-step checkpoint path, absolute or relative to VOSR_DIR
                      (default: preset/ckpts/VOSR_1.4B)
  INCLUDE_ONESTEP     Set to 1 to run the one-step baseline comparator (default: 0)
  PYTHON_BIN          Python executable (default: python)
  UPSCALE             Upscale factor (default: 4)
  INFER_STEPS         Multi-step evaluations (default: 25)
  SEED                Shared seed for all profiles (default: 42)
  TILE_SIZE           DiT tile size; 0 disables tiling (default: 256)
  VAE_TILE_SIZE       VAE tile size; 0 disables VAE tiling (default: 1024)

Profiles:
  natural   cfg=0.50  weak=0.10  steps=$INFER_STEPS
  fidelity  cfg=1.25  weak=0.18  steps=$INFER_STEPS
  strict    cfg=1.75  weak=0.23  steps=$INFER_STEPS
  onestep   cfg=1.00  weak=0.00  steps=1 (optional baseline comparator)
USAGE
}

INPUT=""
OUTPUT_ROOT="vosr-fidelity-sweep"
INCLUDE_ONESTEP=${INCLUDE_ONESTEP:-0}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help)
      usage
      exit 0
      ;;
    --include-onestep)
      INCLUDE_ONESTEP=1
      shift
      ;;
    *)
      if [[ -z "$INPUT" ]]; then
        INPUT="$1"
      elif [[ "$OUTPUT_ROOT" == "vosr-fidelity-sweep" ]]; then
        OUTPUT_ROOT="$1"
      else
        echo "error: unexpected argument: $1" >&2
        usage >&2
        exit 2
      fi
      shift
      ;;
  esac
done

VOSR_DIR=${VOSR_DIR:-"$HOME/VOSR"}
VOSR_CKPT=${VOSR_CKPT:-preset/ckpts/VOSR_1.4B_ms}
VOSR_ONESTEP_CKPT=${VOSR_ONESTEP_CKPT:-}
PYTHON_BIN=${PYTHON_BIN:-python}
UPSCALE=${UPSCALE:-4}
INFER_STEPS=${INFER_STEPS:-25}
SEED=${SEED:-42}
TILE_SIZE=${TILE_SIZE:-256}
VAE_TILE_SIZE=${VAE_TILE_SIZE:-1024}

if [[ -z "$INPUT" ]]; then
  usage >&2
  exit 2
fi
if [[ ! -f "$INPUT" ]]; then
  echo "error: input image not found: $INPUT" >&2
  exit 2
fi
if [[ ! -d "$VOSR_DIR" ]]; then
  echo "error: VOSR checkout not found: $VOSR_DIR" >&2
  exit 2
fi
if [[ ! -f "$VOSR_DIR/inference_vosr.py" ]]; then
  echo "error: inference_vosr.py missing under: $VOSR_DIR" >&2
  exit 2
fi
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "error: Python executable not found: $PYTHON_BIN" >&2
  exit 2
fi

if [[ "$VOSR_CKPT" = /* ]]; then
  CKPT="$VOSR_CKPT"
else
  CKPT="$VOSR_DIR/$VOSR_CKPT"
fi
if [[ ! -d "$CKPT" ]]; then
  echo "error: VOSR multi-step checkpoint not found: $CKPT" >&2
  exit 2
fi
if [[ ! -f "$CKPT/args.json" ]]; then
  echo "error: checkpoint args.json not found: $CKPT/args.json" >&2
  exit 2
fi

if [[ "$INCLUDE_ONESTEP" == "1" ]]; then
  if [[ -n "$VOSR_ONESTEP_CKPT" ]]; then
    if [[ "$VOSR_ONESTEP_CKPT" = /* ]]; then
      ONESTEP_CKPT="$VOSR_ONESTEP_CKPT"
    else
      ONESTEP_CKPT="$VOSR_DIR/$VOSR_ONESTEP_CKPT"
    fi
  elif [[ -d "$VOSR_DIR/preset/ckpts/VOSR_1.4B" && -f "$VOSR_DIR/preset/ckpts/VOSR_1.4B/args.json" ]]; then
    ONESTEP_CKPT="$VOSR_DIR/preset/ckpts/VOSR_1.4B"
  else
    ONESTEP_CKPT="$CKPT"
  fi
  if [[ ! -d "$ONESTEP_CKPT" || ! -f "$ONESTEP_CKPT/args.json" ]]; then
    echo "error: VOSR one-step checkpoint not found: $ONESTEP_CKPT" >&2
    exit 2
  fi
fi

mkdir -p "$OUTPUT_ROOT"
INPUT_ABS=$("$PYTHON_BIN" - "$INPUT" <<'PY'
import os, sys
print(os.path.abspath(sys.argv[1]))
PY
)
OUTPUT_ABS=$("$PYTHON_BIN" - "$OUTPUT_ROOT" <<'PY'
import os, sys
print(os.path.abspath(sys.argv[1]))
PY
)
INPUT_STEM=$("$PYTHON_BIN" - "$INPUT_ABS" <<'PY'
from pathlib import Path
import sys
print(Path(sys.argv[1]).stem)
PY
)

TMP_ROOT=$(mktemp -d "${TMPDIR:-/tmp}/fidelis-vsweep.XXXXXX")
trap 'rm -rf "$TMP_ROOT"' EXIT

make_profile_ckpt() {
  local name=$1 weak=$2 target_ckpt=${3:-$CKPT}
  local profile_ckpt="$TMP_ROOT/$name"
  mkdir -p "$profile_ckpt"

  "$PYTHON_BIN" - "$target_ckpt/args.json" "$profile_ckpt/args.json" "$weak" <<'PY'
import json, pathlib, sys
src, dst, weak = sys.argv[1], sys.argv[2], float(sys.argv[3])
data = json.loads(pathlib.Path(src).read_text())
# The current upstream multi-step sampler reads weak_cond_strength_aelq_list,
# not the scalar CLI value. Pin both endpoints to the requested profile value.
data["weak_cond_strength_aelq"] = weak
data["weak_cond_strength_aelq_list"] = [weak, weak]
pathlib.Path(dst).write_text(json.dumps(data, indent=2) + "\n")
PY

  for child in checkpoints clean_weights; do
    if [[ -e "$target_ckpt/$child" ]]; then
      ln -s "$target_ckpt/$child" "$profile_ckpt/$child"
    fi
  done
  # Fallback for unusual checkpoint layouts with weights directly in the root.
  find "$target_ckpt" -maxdepth 1 -type f \( -name '*.safetensors' -o -name '*.pth' -o -name '*.pt' \) -print0 |
    while IFS= read -r -d '' weight; do
      ln -s "$weight" "$profile_ckpt/$(basename "$weight")"
    done

  printf '%s\n' "$profile_ckpt"
}

run_profile() {
  local name=$1 cfg=$2 weak=$3 steps=${4:-$INFER_STEPS} target_ckpt=${5:-$CKPT}
  local out="$OUTPUT_ABS/$name"
  local log="$OUTPUT_ABS/${name}.log"
  local expected="$out/${INPUT_STEM}.png"
  local profile_ckpt
  profile_ckpt=$(make_profile_ckpt "$name" "$weak" "$target_ckpt")
  rm -rf "$out"
  mkdir -p "$out"

  printf '\n==> %s  cfg=%s  weak=%s  steps=%s\n' "$name" "$cfg" "$weak" "$steps"
  printf '    log: %s\n' "$log"

  set +e
  (
    cd "$VOSR_DIR"
    INFER_NO_SKIP=1 "$PYTHON_BIN" inference_vosr.py \
      -c "$profile_ckpt" \
      -i "$INPUT_ABS" \
      -o "$out" \
      -u "$UPSCALE" \
      --infer_steps "$steps" \
      --cfg_scale "$cfg" \
      --weak_cond_strength_aelq "$weak" \
      --seed "$SEED" \
      --align_method wavelet \
      --posterior_mode \
      --tile_size "$TILE_SIZE" \
      --vae_tile_size "$VAE_TILE_SIZE" \
      --force_rerun
  ) 2>&1 | tee "$log"
  local rc=${PIPESTATUS[0]}
  set -e

  if [[ $rc -ne 0 ]]; then
    echo "error: VOSR process failed for profile '$name' with exit code $rc" >&2
    exit "$rc"
  fi

  # Upstream VOSR catches per-image exceptions and may still exit 0. Therefore
  # a real output file, not the process return code, is the success criterion.
  if [[ ! -s "$expected" ]]; then
    echo >&2
    echo "error: profile '$name' exited without producing $expected" >&2
    echo "The upstream inference script may have caught an image-level exception." >&2
    echo "Last 80 log lines:" >&2
    tail -n 80 "$log" >&2 || true
    exit 70
  fi

  "$PYTHON_BIN" - "$expected" <<'PY'
from PIL import Image
import pathlib, sys
p = pathlib.Path(sys.argv[1])
with Image.open(p) as im:
    im.verify()
with Image.open(p) as im:
    print(f"verified: {p.name} | {im.width}x{im.height} | {p.stat().st_size / 1024**2:.2f} MB")
PY
}

run_profile natural 0.50 0.10 "$INFER_STEPS" "$CKPT"
run_profile fidelity 1.25 0.18 "$INFER_STEPS" "$CKPT"
run_profile strict 1.75 0.23 "$INFER_STEPS" "$CKPT"

if [[ "$INCLUDE_ONESTEP" == "1" ]]; then
  run_profile onestep 1.00 0.00 1 "$ONESTEP_CKPT"
fi

"$PYTHON_BIN" - "$INPUT_ABS" "$OUTPUT_ABS" "$CKPT" "$UPSCALE" "$INFER_STEPS" "$SEED" "$TILE_SIZE" "$VAE_TILE_SIZE" "$INCLUDE_ONESTEP" <<'PY'
import hashlib, json, pathlib, sys, time

inp, root, ckpt, upscale, steps, seed, tile, vae_tile, inc_onestep = sys.argv[1:10]
root = pathlib.Path(root)
profiles = {
    "natural": {"cfg_scale": 0.50, "weak_cond_strength_aelq": 0.10, "infer_steps": int(steps)},
    "fidelity": {"cfg_scale": 1.25, "weak_cond_strength_aelq": 0.18, "infer_steps": int(steps)},
    "strict": {"cfg_scale": 1.75, "weak_cond_strength_aelq": 0.23, "infer_steps": int(steps)},
}
if inc_onestep == "1":
    profiles["onestep"] = {"cfg_scale": 1.00, "weak_cond_strength_aelq": 0.00, "infer_steps": 1}

def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

outputs = {}
for name in profiles:
    files = sorted(p for p in (root / name).glob("*.png") if p.is_file())
    if not files:
        raise SystemExit(f"refusing to write success manifest: no PNG output for {name}")
    outputs[name] = [
        {"path": str(p), "bytes": p.stat().st_size, "sha256": sha256(p)}
        for p in files
    ]

manifest = {
    "created_unix": int(time.time()),
    "input": {"path": inp, "sha256": sha256(inp)},
    "checkpoint": ckpt,
    "upscale": int(upscale),
    "infer_steps": int(steps),
    "seed": int(seed),
    "tile_size": int(tile),
    "vae_tile_size": int(vae_tile),
    "align_method": "wavelet",
    "posterior_mode": True,
    "post_processing": "none",
    "profiles": profiles,
    "outputs": outputs,
}
(root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
print(f"\nmanifest: {root / 'manifest.json'}")
for name, files in outputs.items():
    print(f"{name}: {len(files)} PNG output(s)")
PY

count=3
if [[ "$INCLUDE_ONESTEP" == "1" ]]; then
  count=4
fi
printf '\nDone. %d verified PNG output(s) were produced.\n' "$count"
printf 'No sharpening, face restoration, source fusion, denoise, or synthetic grain was applied.\n'
