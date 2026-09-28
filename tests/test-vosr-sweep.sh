#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
sweep="$repo_root/experiments/vosr-fidelity-sweep.sh"
work="$(mktemp -d "${TMPDIR:-/tmp}/fidelis-sweep-test.XXXXXX")"
trap 'rm -rf "$work"' EXIT

fake_vosr="$work/VOSR"
ckpt="$fake_vosr/preset/ckpts/VOSR_1.4B_ms"
mkdir -p "$ckpt/checkpoints"
printf 'fake weights\n' > "$ckpt/checkpoints/ema_model.safetensors"
cat > "$ckpt/args.json" <<'JSON'
{
  "weak_cond_strength_aelq": 0.1,
  "weak_cond_strength_aelq_list": [0.05, 0.25]
}
JSON

cat > "$fake_vosr/inference_vosr.py" <<'PY'
import argparse
import json
import os
from pathlib import Path
from PIL import Image

p = argparse.ArgumentParser()
p.add_argument('-c', '--checkpoint', required=True)
p.add_argument('-i', '--input_image', required=True)
p.add_argument('-o', '--output_dir', required=True)
p.add_argument('-u', '--upscale')
p.add_argument('--infer_steps')
p.add_argument('--cfg_scale')
p.add_argument('--weak_cond_strength_aelq')
p.add_argument('--seed')
p.add_argument('--align_method')
p.add_argument('--posterior_mode', action='store_true')
p.add_argument('--tile_size')
p.add_argument('--vae_tile_size')
p.add_argument('--force_rerun', action='store_true')
args, _ = p.parse_known_args()

out = Path(args.output_dir)
profile = out.name
config = json.loads((Path(args.checkpoint) / 'args.json').read_text())
print(
    'PROFILE=' + profile,
    'CFG=' + str(args.cfg_scale),
    'WEAK_SCALAR=' + str(args.weak_cond_strength_aelq),
    'WEAK_LIST=' + json.dumps(config.get('weak_cond_strength_aelq_list')),
)

# Simulate upstream VOSR's dangerous behavior: an image-level exception can be
# printed while the process still exits successfully.
if os.environ.get('FAKE_FAIL_PROFILE') == profile:
    print(f'Error processing {Path(args.input_image).name}: synthetic swallowed error')
    raise SystemExit(0)

out.mkdir(parents=True, exist_ok=True)
Image.new('RGB', (2, 2), (32, 64, 96)).save(out / (Path(args.input_image).stem + '.png'))
print('Done!')
PY

input="$work/test.jpg"
python3 - "$input" <<'PY'
from PIL import Image
import sys
Image.new('RGB', (3, 2), (120, 110, 100)).save(sys.argv[1], quality=90)
PY

results="$work/results"
VOSR_DIR="$fake_vosr" \
VOSR_CKPT="preset/ckpts/VOSR_1.4B_ms" \
PYTHON_BIN="python3" \
TILE_SIZE=256 \
VAE_TILE_SIZE=1024 \
bash "$sweep" "$input" "$results"

for profile in natural fidelity strict; do
  test -s "$results/$profile/test.png"
  test -s "$results/$profile.log"
done
test -s "$results/manifest.json"

python3 - "$results/manifest.json" <<'PY'
import json
import sys
m = json.load(open(sys.argv[1]))
expected = {
    'natural': (0.50, 0.10),
    'fidelity': (1.25, 0.18),
    'strict': (1.75, 0.23),
}
assert m['tile_size'] == 256
assert m['vae_tile_size'] == 1024
for name, (cfg, weak) in expected.items():
    assert m['profiles'][name]['cfg_scale'] == cfg
    assert m['profiles'][name]['weak_cond_strength_aelq'] == weak
    assert len(m['outputs'][name]) == 1
    assert m['outputs'][name][0]['bytes'] > 0
print('success manifest verified')
PY

grep -Fq 'WEAK_LIST=[0.1, 0.1]' "$results/natural.log"
grep -Fq 'WEAK_LIST=[0.18, 0.18]' "$results/fidelity.log"
grep -Fq 'WEAK_LIST=[0.23, 0.23]' "$results/strict.log"

# Regression: a swallowed upstream image error must never become a success
# manifest or an empty ZIP candidate.
rm -rf "$results"
set +e
FAKE_FAIL_PROFILE=fidelity \
VOSR_DIR="$fake_vosr" \
VOSR_CKPT="preset/ckpts/VOSR_1.4B_ms" \
PYTHON_BIN="python3" \
bash "$sweep" "$input" "$results" >"$work/failure.out" 2>&1
rc=$?
set -e

if [[ $rc -eq 0 ]]; then
  echo 'expected swallowed-image failure to be rejected, but sweep returned success' >&2
  cat "$work/failure.out" >&2
  exit 1
fi
if [[ -e "$results/manifest.json" ]]; then
  echo 'failure run must not produce a success manifest' >&2
  exit 1
fi
grep -Fq "profile 'fidelity' exited without producing" "$work/failure.out"
grep -Fq 'synthetic swallowed error' "$work/failure.out"

printf 'VOSR sweep regression tests passed.\n'
