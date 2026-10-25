#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
work="$(mktemp -d "${TMPDIR:-/tmp}/fidelis-drift-test.XXXXXX")"
trap 'rm -rf "$work"' EXIT

python_bin="${PYTHON_BIN:-}"
if [[ -z "$python_bin" ]]; then
  if [[ -x "$repo_root/.venv/bin/python" ]]; then
    python_bin="$repo_root/.venv/bin/python"
  elif python3 -c "import scipy" >/dev/null 2>&1; then
    python_bin="python3"
  else
    python_bin="python3"
  fi
fi

src="$work/src.png"
out_stable="$work/out_stable.png"
out_drift="$work/out_drift.png"

"$python_bin" - "$src" "$out_stable" "$out_drift" "$repo_root" <<'PY'
import sys
from pathlib import Path
from PIL import Image
import numpy as np

src_out, stable_out, drift_out, repo_root = sys.argv[1:5]
fixture_path = Path(repo_root) / "tests/fixtures/portrait_skin.png"

if fixture_path.is_file():
    im = Image.open(fixture_path)
    # Downscale by 4x as test source
    src_im = im.resize((im.width // 4, im.height // 4), Image.Resampling.LANCZOS)
    src_im.save(src_out)
    # Stable 4x upscaled reference
    stable_im = src_im.resize((im.width, im.height), Image.Resampling.LANCZOS)
    stable_im.save(stable_out)
else:
    # Synthetic gradient pattern
    arr = np.linspace(0, 255, 64, dtype=np.uint8)
    grid = np.tile(arr, (64, 1))
    src_im = Image.fromarray(grid)
    src_im.save(src_out)
    stable_im = src_im.resize((256, 256), Image.Resampling.LANCZOS)
    stable_im.save(stable_out)

# Heavily drifted output: roll horizontally by 20px and introduce noise
arr_stable = np.asarray(stable_im)
arr_drift = np.roll(arr_stable, 20, axis=1)
drift_im = Image.fromarray(arr_drift)
drift_im.save(drift_out)
PY

results="$work/results"
mkdir -p "$results"
cp "$out_stable" "$results/ModelStable.png"
cp "$out_drift" "$results/ModelDrift.png"

cat > "$results/manifest.json" <<EOF
{
  "schema_version": 1,
  "input": {
    "path": "$src",
    "filename": "src.png"
  },
  "entries": [
    {
      "model": {"name": "ModelStable"},
      "output": {"filename": "ModelStable.png"}
    },
    {
      "model": {"name": "ModelDrift"},
      "output": {"filename": "ModelDrift.png"}
    }
  ]
}
EOF

# 1. Test directory evaluation via bin/fidelis detect-drift
"$repo_root/bin/fidelis" detect-drift "$results"
test -s "$results/drift_analysis.json"

jq -e '
  has("ModelStable")
  and has("ModelDrift")
  and (.ModelStable.gradient_coherence_pct > 80.0)
  and (.ModelStable.status | contains("PASS"))
  and (.ModelDrift.status | contains("FAIL"))
' "$results/drift_analysis.json" >/dev/null

# 2. Test single pair via detect-drift.py
"$python_bin" "$repo_root/scripts/detect-drift.py" "$src" -o "$out_stable" > "$work/single_stable.json"
jq -e '.gradient_coherence_pct > 80.0 and (.status | contains("PASS"))' "$work/single_stable.json" >/dev/null

# 3. Test strict mode exit failure on drifted image
set +e
"$python_bin" "$repo_root/scripts/detect-drift.py" "$src" -o "$out_drift" --strict >/dev/null 2>&1
status=$?
set -e
if [[ $status -eq 0 ]]; then
  echo "Expected strict drift detection to fail, but it exited 0!" >&2
  exit 1
fi

printf 'Geometric & identity drift detector tests passed.\n'
