#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"

python_bin="${PYTHON_BIN:-}"
if [[ -z "$python_bin" ]]; then
  if [[ -x "$repo_root/.venv/bin/python" ]]; then
    python_bin="$repo_root/.venv/bin/python"
  else
    python_bin="python3"
  fi
fi

printf 'Testing Fidelis Self-Improvement & Degradation Pipeline...\n'

# 1. Test Degradation Generator
"$python_bin" -c '
import cv2, numpy as np
from fidelis.data.degradation import DegradationGenerator

gen = DegradationGenerator(scale=4, seed=123)
dummy_hr = np.full((256, 256, 3), 128, dtype=np.uint8)
cv2.rectangle(dummy_hr, (50, 50), (200, 200), (255, 0, 0), -1)

lr1, hr1 = gen.generate_pair(dummy_hr, second_order=False)
assert lr1.shape == (64, 64, 3), f"Bad LR1 shape: {lr1.shape}"

lr2, hr2 = gen.generate_pair(dummy_hr, second_order=True)
assert lr2.shape == (64, 64, 3), f"Bad LR2 shape: {lr2.shape}"
print("Degradation generator verified successfully.")
'

# 2. Test Evaluation Corpus
"$python_bin" -c '
from fidelis.eval.corpus import EvaluationCorpus, TestBucket

corpus = EvaluationCorpus()
assert len(corpus.items) > 0, "No corpus items discovered"
summary = corpus.list_summary()
print("Corpus summary:", summary)
assert summary[TestBucket.PORTRAIT_SKIN.value] > 0, "Portrait bucket missing"
'

# 3. Test Self-Improvement CLI
out_dir="$(mktemp -d /tmp/fidelis_si_test_XXXXXX)"
trap 'rm -rf "$out_dir"' EXIT

"$repo_root/bin/fidelis" self-improve -n 1 -o "$out_dir"

[[ -f "$out_dir/manifest.json" ]]
[[ -f "$out_dir/self_improvement_report.html" ]]

"$python_bin" -c '
import json, sys
with open(sys.argv[1]) as f:
    data = json.load(f)
assert "summary" in data, "manifest missing summary"
assert data["summary"]["items_evaluated"] >= 1, "no items evaluated"
print("Self-improvement manifest verified successfully.")
' "$out_dir/manifest.json"

printf 'All Fidelis self-improvement tests passed successfully.\n'
