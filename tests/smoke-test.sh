#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
python_bin="$repo_root/.venv/bin/python"
if [ ! -x "$python_bin" ]; then
  python_bin="$(command -v python3 || command -v python)"
fi

bash -n "$repo_root/install.sh"
bash -n "$repo_root/bin/fidelis"
bash -n "$repo_root/scripts/detect-vulkan.sh"
bash -n "$repo_root/scripts/install-photo-candidate.sh"
bash -n "$repo_root/scripts/install-macos-runtime.sh"
bash -n "$repo_root/scripts/benchmark-photo-candidates.sh"
bash -n "$repo_root/scripts/batch-audition.sh"
bash -n "$repo_root/scripts/adb-device-benchmark.sh"
bash -n "$repo_root/scripts/macos-benchmark.sh"
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
bash -n "$repo_root/tests/test-release-pipeline.sh"
bash -n "$repo_root/tests/test-browser-acceptance.sh"

"$python_bin" -m py_compile "$repo_root/scripts/generate-delta-heatmap.py"
"$python_bin" -m py_compile "$repo_root/scripts/detect-drift.py"
"$python_bin" -m py_compile "$repo_root/scripts/tiled-upscale.py"
"$python_bin" -m py_compile "$repo_root/scripts/evaluate-fidelity-metrics.py"
"$python_bin" -m py_compile "$repo_root/scripts/generate-audition-report.py"
"$python_bin" -m py_compile "$repo_root/scripts/generate-master-dashboard.py"
"$python_bin" -m py_compile "$repo_root/scripts/web-ui.py"
"$python_bin" -m py_compile "$repo_root/scripts/fetch-eval-crops.py"
"$python_bin" -m py_compile "$repo_root/scripts/reblend-regions.py"
"$python_bin" -m py_compile "$repo_root/scripts/export-studio-batch.py"
"$python_bin" -m py_compile "$repo_root/scripts/generate-texture.py"
"$python_bin" -m py_compile "$repo_root/scripts/structural-roi.py"
"$python_bin" -m py_compile "$repo_root/scripts/audit-model-provenance.py"
"$python_bin" -m py_compile "$repo_root/scripts/worker-preflight.py"
"$python_bin" -m py_compile "$repo_root/scripts/screen-roi-drift.py"
"$python_bin" -m py_compile "$repo_root/scripts/export-master.py"
"$python_bin" -m py_compile "$repo_root/scripts/run-comparators.py"
"$python_bin" -m py_compile "$repo_root/scripts/evaluate-quality-acceptance.py"
"$python_bin" -m py_compile "$repo_root/scripts/batch-run.py"
"$python_bin" -m py_compile "$repo_root/scripts/verify-upgrade-rollback.py"
"$python_bin" -m py_compile "$repo_root/scripts/audit-release-readiness.py"

"$python_bin" -m json.tool "$repo_root/notebooks/Fidelis_VOSR_MultiStep_Sweep_Colab.ipynb" >/dev/null

# Installer invariants for the current ARM64 lane.
grep -q 'GUI-armv8a' "$repo_root/install.sh"
grep -q 'models-ESRGAN-Nomos8kSC' "$repo_root/install.sh"
grep -q 'checksum mismatch' "$repo_root/install.sh"

# CLI must remain capable of selecting and auditioning candidate models.
grep -q 'fidelis audition INPUT OUTPUT_DIR' "$repo_root/bin/fidelis"
grep -q 'fidelis batch-audition INPUT_DIR OUTPUT_DIR' "$repo_root/bin/fidelis"
grep -q 'fidelis detect-drift RESULTS_DIR' "$repo_root/bin/fidelis"
grep -q 'fidelis heatmap SOURCE' "$repo_root/bin/fidelis"
grep -q 'FIDELIS_MODEL' "$repo_root/bin/fidelis"

# Quality-reference invariants. These prevent a future refactor from silently
# reintroducing the failed source-fusion path or accepting empty VOSR outputs.
grep -q "weak_cond_strength_aelq_list" "$repo_root/experiments/vosr-fidelity-sweep.sh"
grep -q "exited without producing" "$repo_root/experiments/vosr-fidelity-sweep.sh"
grep -q 'post_processing.*none' "$repo_root/experiments/vosr-fidelity-sweep.sh"

printf 'Static smoke tests passed.\n'
