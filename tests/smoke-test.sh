#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"

bash -n "$repo_root/install.sh"
bash -n "$repo_root/bin/fidelis"
bash -n "$repo_root/scripts/detect-vulkan.sh"
bash -n "$repo_root/experiments/vosr-fidelity-sweep.sh"
bash -n "$repo_root/tests/test-vosr-sweep.sh"

python3 -m json.tool "$repo_root/notebooks/Fidelis_VOSR_MultiStep_Sweep_Colab.ipynb" >/dev/null

# Installer invariants for the current ARM64 lane.
grep -q 'GUI-armv8a' "$repo_root/install.sh"
grep -q 'models-ESRGAN-Nomos8kSC' "$repo_root/install.sh"
grep -q 'checksum mismatch' "$repo_root/install.sh"

# Quality-reference invariants. These prevent a future refactor from silently
# reintroducing the failed source-fusion path or accepting empty VOSR outputs.
grep -q "weak_cond_strength_aelq_list" "$repo_root/experiments/vosr-fidelity-sweep.sh"
grep -q "exited without producing" "$repo_root/experiments/vosr-fidelity-sweep.sh"
grep -q 'post_processing.*none' "$repo_root/experiments/vosr-fidelity-sweep.sh"

printf 'Static smoke tests passed.\n'
