#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"

bash -n "$repo_root/install.sh"
bash -n "$repo_root/bin/fidelis"
bash -n "$repo_root/scripts/detect-vulkan.sh"
bash -n "$repo_root/scripts/install-photo-candidate.sh"
bash -n "$repo_root/scripts/install-macos-runtime.sh"
bash -n "$repo_root/scripts/benchmark-photo-candidates.sh"
bash -n "$repo_root/scripts/batch-audition.sh"
bash -n "$repo_root/scripts/adb-device-benchmark.sh"
bash -n "$repo_root/scripts/package-release.sh"
bash -n "$repo_root/scripts/package-offline-bundle.sh"
bash -n "$repo_root/experiments/vosr-fidelity-sweep.sh"
bash -n "$repo_root/tests/test-cli-model-selection.sh"
bash -n "$repo_root/tests/test-fidelity-metrics.sh"
bash -n "$repo_root/tests/test-audition-report.sh"
bash -n "$repo_root/tests/test-batch-audition.sh"
bash -n "$repo_root/tests/test-detect-drift.sh"
bash -n "$repo_root/tests/test-web-ui.sh"
bash -n "$repo_root/tests/test-vosr-sweep.sh"

python3 -m py_compile "$repo_root/scripts/detect-drift.py"
python3 -m py_compile "$repo_root/scripts/tiled-upscale.py"
python3 -m py_compile "$repo_root/scripts/evaluate-fidelity-metrics.py"
python3 -m py_compile "$repo_root/scripts/generate-audition-report.py"
python3 -m py_compile "$repo_root/scripts/generate-master-dashboard.py"
python3 -m py_compile "$repo_root/scripts/web-ui.py"
python3 -m py_compile "$repo_root/scripts/fetch-eval-crops.py"

python3 -m json.tool "$repo_root/notebooks/Fidelis_VOSR_MultiStep_Sweep_Colab.ipynb" >/dev/null

# Installer invariants for the current ARM64 lane.
grep -q 'GUI-armv8a' "$repo_root/install.sh"
grep -q 'models-ESRGAN-Nomos8kSC' "$repo_root/install.sh"
grep -q 'checksum mismatch' "$repo_root/install.sh"

# CLI must remain capable of selecting and auditioning candidate models.
grep -q 'fidelis audition INPUT OUTPUT_DIR' "$repo_root/bin/fidelis"
grep -q 'fidelis batch-audition INPUT_DIR OUTPUT_DIR' "$repo_root/bin/fidelis"
grep -q 'fidelis detect-drift RESULTS_DIR' "$repo_root/bin/fidelis"
grep -q 'FIDELIS_MODEL' "$repo_root/bin/fidelis"

# Quality-reference invariants. These prevent a future refactor from silently
# reintroducing the failed source-fusion path or accepting empty VOSR outputs.
grep -q "weak_cond_strength_aelq_list" "$repo_root/experiments/vosr-fidelity-sweep.sh"
grep -q "exited without producing" "$repo_root/experiments/vosr-fidelity-sweep.sh"
grep -q 'post_processing.*none' "$repo_root/experiments/vosr-fidelity-sweep.sh"

printf 'Static smoke tests passed.\n'
