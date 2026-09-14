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
  TILE_SIZE      DiT tile size; 0 disables tiling (default: 256)
  VAE_TILE_SIZE  VAE tile size; 0 disables VAE tiling (default: 1024)

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
  local name=$1 weak=$2
  local profile_ckpt="$TMP_ROOT/$name"
  mkdir -p "$profile_ckpt"

  "$PYTHON_BIN" - "$CKPT/args.json" "$profile_ckpt/args.json" "$weak" <<'PY'
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
    if [[ -e "$CKPT/$child" ]]; then
      ln -s "$CKPT/$child" "$profile_ckpt/$child"
    fi
  done
  # Fallback for unusual checkpoint layouts with weights directly in the root.
  find "$CKPT" -maxdepth 1 -type f \( -name '*.safetensors' -o -name '*.pth' -o -name '*.pt' \) -print0 |
    while IFS= read -r -d '' weight; do
      ln -s "$weight" "$profile_ckpt/$(basename "$weight")"
    done

  printf '%s\n' "$profile_ckpt"
}

run_profile() {
  local name=$1 cfg=$2 weak=$3
  local out="$OUTPUT_ABS/$name"
  local log="$OUTPUT_ABS/${name}.log"
  local expected="$out/${INPUT_STEM}.png"
  local profile_ckpt
  profile_ckpt=$(make_profile_ckpt "$name" "$weak")
  rm -rf "$out"
  mkdir -p "$out"

  printf '\n==> %s  cfg=%s  weak=%s\n' "$name" "$cfg" "$weak"
  printf '    log: %s\n' "$log"

  set +e
  (
    cd "$VOSR_DIR"
    INFER_NO_SKIP=1 "$PYTHON_BIN" inference_vosr.py \
      -c "$profile_ckpt" \
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

run_profile natural 0.50 0.10
run_profile fidelity 1.25 0.18
run_profile strict 1.75 0.23

"$PYTHON_BIN" - "$INPUT_ABS" "$OUTPUT_ABS" "$CKPT" "$UPSCALE" "$INFER_STEPS" "$SEED" "$TILE_SIZE" "$VAE_TILE_SIZE" <<'PY'
import hashlib, json, pathlib, sys, time

inp, root, ckpt, upscale, steps, seed, tile, vae_tile = sys.argv[1:]
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

printf '\nDone. Three verified PNG outputs were produced.\n'
printf 'No sharpening, face restoration, source fusion, denoise, or synthetic grain was applied.\n'
