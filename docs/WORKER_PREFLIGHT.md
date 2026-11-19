# Reproducible live-worker and workflow schema preflight (`F05-A` / `MEL-76`)

`fidelis/studio/worker_preflight.py` and `scripts/worker-preflight.py` provide a
deterministic, secret-safe preflight for local or SSH-tunneled ComfyUI workers and
exported Studio texture workflows.

## What the preflight verifies

1. **Resource owner, loopback access, and zero-paid-fallback budget policy**
   (`config/worker-preflight-policy-v1.json`):
   - Only `http://127.0.0.1`, `http://localhost`, or `http://[::1]` endpoints are
     permitted (`loopback` or explicit `ssh_tunnel`).
   - Automatic cloud fallback and paid remote spend remain disabled
     (`allow_remote_cloud_fallback: false`, `max_paid_spend_usd: 0.0`).
   - Secret scanning (`find_secret_violations`) blocks URL credentials, query tokens,
     bearer strings, API keys, and secret keys before any receipt is written.
2. **Local capability inventory** (`fidelis/studio/capabilities.py`):
   - Audits local NCNN/Vulkan binaries, `config/photo-candidates.tsv` SHA-256 weights,
     PyTorch availability, and `nvidia-smi` presence.
3. **Worker endpoint capability probe** (`/system_stats` and `/object_info`):
   - Captures ComfyUI version, Python/PyTorch versions, OS, RAM, GPU/MPS device VRAM
     telemetry, installed node class count, and canonical `object_info_sha256`.
4. **Exported workflow schema and model choice verification**:
   - Computes canonical `workflow_sha256`, node count, required node classes, and
     referenced model checkpoints (`ckpt_name`, `unet_name`, `vae_name`, `lora_name`).
   - When the worker is reachable, validates the workflow against live `/object_info`
     using `validate_workflow` and reports any `missing_node_classes`,
     `missing_required_inputs`, or unavailable `model_choice_checks`.

## CLI usage

```bash
# Probe default local worker (http://127.0.0.1:8188) and record receipt:
.venv/bin/python scripts/worker-preflight.py \
  --owner local-operator \
  --access-method loopback \
  --output .cache/worker-preflight-receipt.json

# Validate a specific exported workflow bundle and require qualification:
.venv/bin/python scripts/worker-preflight.py \
  --address http://127.0.0.1:8188 \
  --workflow path/to/exported_workflow_bundle.json \
  --output .cache/worker-preflight-receipt.json \
  --require-qualified
```

## Evidence boundary

- A `"qualified_preflight"` status is **E1 protocol/schema preflight evidence**: it
  proves the worker endpoint responded and all workflow node classes and combo model
  choices are installed.
- It sets `"live_inference_verified": false` and `"visual_quality_certified": false`.
  Actual GPU image generation (`E2`) and human visual acceptance (`E3`) remain separate
  gates under `F05` and `F06`.
