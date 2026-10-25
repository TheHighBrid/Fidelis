#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
work="$(mktemp -d "${TMPDIR:-/tmp}/fidelis-metrics-test.XXXXXX")"
trap 'rm -rf "$work"' EXIT

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

# Create mock source and output
src="$work/src.png"
out="$work/out.png"
"$python_bin" - "$src" "$out" <<'PY'
from PIL import Image
import sys
Image.new('RGB', (32, 32), (100, 150, 200)).save(sys.argv[1])
Image.new('RGB', (128, 128), (105, 148, 195)).save(sys.argv[2])
PY

results="$work/results"
mkdir -p "$results"
cp "$out" "$results/CandidateA.png"

# Write minimal manifest
cat > "$results/manifest.json" <<EOF
{
  "schema_version": 1,
  "input": {
    "path": "$src",
    "bytes": 512,
    "sha256": "fakeinputhash"
  },
  "entries": [
    {
      "model": {"name": "CandidateA"},
      "output": {"path": "$results/CandidateA.png", "bytes": 1024, "sha256": "fakeouthash"}
    }
  ]
}
EOF

"$python_bin" "$repo_root/scripts/evaluate-fidelity-metrics.py" "$results"
test -s "$results/metrics.json"

jq -e '
  has("CandidateA.png")
  and (.["CandidateA.png"].psnr_db > 0)
  and (.["CandidateA.png"].color_drift >= 0)
' "$results/metrics.json" >/dev/null

printf 'Fidelity metrics evaluation tests passed.\n'
