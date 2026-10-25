#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
work="$(mktemp -d "${TMPDIR:-/tmp}/fidelis-report-test.XXXXXX")"
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

# Create mock audition outputs and manifest
src="$work/source.png"
out_a="$work/results/CandidateA.png"
out_b="$work/results/CandidateB.png"
mkdir -p "$work/results"

"$python_bin" - "$src" "$out_a" "$out_b" <<'PY'
from PIL import Image
import sys
Image.new('RGB', (16, 16), (10, 20, 30)).save(sys.argv[1])
Image.new('RGB', (64, 64), (12, 22, 32)).save(sys.argv[2])
Image.new('RGB', (64, 64), (14, 24, 34)).save(sys.argv[3])
PY

cat > "$work/results/manifest.json" <<EOF
{
  "schema_version": 1,
  "input": {
    "path": "$src",
    "bytes": 256,
    "sha256": "feedbeef12345678"
  },
  "entries": [
    {
      "model": {"name": "CandidateA", "candidate": {"role": "mobile"}},
      "output": {"path": "$out_a", "bytes": 1024, "sha256": "aaa111"}
    },
    {
      "model": {"name": "CandidateB", "candidate": {"role": "fidelity"}},
      "output": {"path": "$out_b", "bytes": 2048, "sha256": "bbb222"}
    }
  ]
}
EOF

report_file="$work/results/report.html"
"$python_bin" "$repo_root/scripts/generate-audition-report.py" "$work/results" -o "$report_file"

test -s "$report_file"
grep -Fq 'Fidelis Visual Audition & Benchmark Report' "$report_file"
grep -Fq 'CandidateA' "$report_file"
grep -Fq 'CandidateB' "$report_file"
grep -Fq 'data:image/png;base64,' "$report_file"

printf 'Audition report generator tests passed.\n'
