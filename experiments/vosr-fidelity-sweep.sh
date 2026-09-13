#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  vosr-fidelity-sweep.sh INPUT_IMAGE [OUTPUT_DIR]

Environment overrides:
  VOSR_DIR       Path to cswry/VOSR checkout (default: $HOME/VOSR)
  VOSR_CKPT      Multi-step checkpoint path, absolute or relative to VOSR_DIR
                 (default: preset/ckpts/VOSR_1.4B_ms)
  PYTHON_BIN     Python executable (default: python)
  UPSCALE        Upscale factor (default: 4)
  INFER_STEPS    Multi-step evaluations (default: 25)
  SEED           Shared seed for all profiles (default: 42)
  TILE_SIZE      DiT tile size; 0 disables tiling (default: 0)

Profiles:
  natural   cfg=0.50  weak=0.10
  fidelity  cfg=1.25  weak=0.18
  strict    cfg=1.75  weak=0.23
USAGE
}

if [[ ${1:-} == "-h" || ${1:-} == "--help" ]]; then
  usage
  exit 0
fi

INPUT=${1:-}
OUTPUT_ROOT=${2:-vosr-fidelity-sweep}
VOSR_DIR=${VOSR_DIR:-"$HOME/VOSR"}
VOSR_CKPT=${VOSR_CKPT:-preset/ckpts/VOSR_1.4B_ms}
PYTHON_BIN=${PYTHON_BIN:-python}
UPSCALE=${UPSCALE:-4}
INFER_STEPS=${INFER_STEPS:-25}
SEED=${SEED:-42}
TILE_SIZE=${TILE_SIZE:-0}

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

if [[ "$VOSR_CKPT" = /* ]]; then
  CKPT="$VOSR_CKPT"
else
  CKPT="$VOSR_DIR/$VOSR_CKPT"
fi
if [[ ! -d "$CKPT" ]]; then
  echo "error: VOSR multi-step checkpoint not found: $CKPT" >&2
  exit 2
fi

mkdir -p "$OUTPUT_ROOT"
INPUT_ABS=$(python - "$INPUT" <<'PY'
import os, sys
print(os.path.abspath(sys.argv[1]))
PY
)
OUTPUT_ABS=$(python - "$OUTPUT_ROOT" <<'PY'
import os, sys
print(os.path.abspath(sys.argv[1]))
PY
)

run_profile() {
  local name=$1 cfg=$2 weak=$3
  local out="$OUTPUT_ABS/$name"
  mkdir -p "$out"

  printf '\n==> %s  cfg=%s  weak=%s\n' "$name" "$cfg" "$weak"
  (
    cd "$VOSR_DIR"
    "$PYTHON_BIN" inference_vosr.py \
      -c "$CKPT" \
      -i "$INPUT_ABS" \
      -o "$out" \
      -u "$UPSCALE" \
      --infer_steps "$INFER_STEPS" \
      --cfg_scale "$cfg" \
      --weak_cond_strength_aelq "$weak" \
      --seed "$SEED" \
      --align_method wavelet \
      --posterior_mode \
      --tile_size "$TILE_SIZE" \
      --force_rerun
  )
}

run_profile natural 0.50 0.10
run_profile fidelity 1.25 0.18
run_profile strict 1.75 0.23

"$PYTHON_BIN" - "$INPUT_ABS" "$OUTPUT_ABS" "$CKPT" "$UPSCALE" "$INFER_STEPS" "$SEED" "$TILE_SIZE" <<'PY'
import hashlib, json, pathlib, sys, time

inp, root, ckpt, upscale, steps, seed, tile = sys.argv[1:]
root = pathlib.Path(root)
profiles = {
    "natural": {"cfg_scale": 0.50, "weak_cond_strength_aelq": 0.10},
    "fidelity": {"cfg_scale": 1.25, "weak_cond_strength_aelq": 0.18},
    "strict": {"cfg_scale": 1.75, "weak_cond_strength_aelq": 0.23},
}

def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

outputs = {}
for name in profiles:
    files = sorted(p for p in (root / name).glob("*.png") if p.is_file())
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

printf '\nDone. Compare the three PNG outputs at 100%% and 200%% crops.\n'
printf 'No sharpening, face restoration, source fusion, denoise, or synthetic grain was applied.\n'
