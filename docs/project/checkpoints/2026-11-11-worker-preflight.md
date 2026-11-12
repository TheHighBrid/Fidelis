# Checkpoint receipt · Live-worker and workflow schema preflight (`F05-A` / `MEL-76`)

- **Date**: 2026-11-11
- **Task**: `F05-A` / Linear `MEL-76` (*Prepare a reproducible live-worker preflight*)
- **Branch**: `work/mel-76-live-worker-preflight` (branched from `origin/feat/region-aware-studio` at `c4cf1bd`)
- **Evidence level**: `E1` (deterministic unit, CLI, secret-redaction, and mock HTTP protocol tests; no live GPU worker is connected to this executor)

## What changed

1. **Explicit worker access and budget policy (`config/worker-preflight-policy-v1.json`)**:
   - Enforces loopback/SSH-tunnel endpoints (`127.0.0.1`, `localhost`, `::1`), explicit
     resource owner/access metadata, `allow_remote_cloud_fallback: false`,
     `max_paid_spend_usd: 0.0`, and `secret_storage_policy: "forbid_repo_secrets"`.
2. **Preflight verifier and secret guard (`fidelis/studio/worker_preflight.py`)**:
   - `find_secret_violations` rejects URL userinfo/query tokens, bearer headers, API key
     patterns, and forbidden secret keys in requests, workflows, and emitted receipts.
   - `inspect_workflow_bundle` audits exported ComfyUI workflow bundles both offline
     (digest, node count, required node classes, referenced model identifiers) and
     against live `/object_info` (missing node classes, missing required inputs, and
     installed combo choices for checkpoints/VAEs/LoRAs).
   - `run_worker_preflight` combines local `capabilities.inventory`, worker
     `/system_stats` + `/object_info` probing, policy validation, and workflow schema
     checks into a `fidelis.worker_preflight.v1` receipt.
3. **CLI and test suite (`scripts/worker-preflight.py`, `tests/test_worker_preflight.py`, `docs/WORKER_PREFLIGHT.md`)**:
   - Added CLI flags `--address`, `--workflow`, `--policy`, `--owner`,
     `--access-method`, `--output`, `--require-reachable`, and `--require-qualified`.
   - Added 5 unit/protocol tests covering reachable qualification, missing checkpoint /
     custom node detection, offline worker fallback, secret/policy rejection, and CLI
     exit codes.

## Verification

- `.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v`: **132 passed**
- `PATH="$PWD/.venv/bin:$PATH" bash tests/test-web-ui.sh`: passed
- `PATH="$PWD/.venv/bin:$PATH" bash tests/smoke-test.sh`: passed
- `git diff --check`: passed

## Actual local probe result & remaining gate

- Running `.venv/bin/python scripts/worker-preflight.py` on this executor reports
  `preflight_status: "worker_unreachable"` (`ConnectError` on `http://127.0.0.1:8188`),
  `ncnn_executable: false`, `torch_importable: true`, `nvidia_smi_present: false`, and
  `live_inference_verified: false`.
- **Next concrete action**: Run `scripts/worker-preflight.py --workflow <bundle.json> --require-qualified`
  against the target GPU/Apple Silicon ComfyUI worker once attached, then proceed to
  `F05`/`F06` golden-image live inference audition.
