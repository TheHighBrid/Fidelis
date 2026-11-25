# Checkpoint receipt · Live ComfyUI MPS worker preflight (`F05-A` / `MEL-76`)

- **Date**: 2026-11-24
- **Task**: `F05-A` / Linear `MEL-76` (*Prepare a reproducible live-worker preflight*)
- **Base SHA**: `f0b1ed2` (`origin/main`)
- **Branch**: `work/mel-76-live-worker-preflight`
- **Evidence level**: `E1_preflight_protocol_only` (live endpoint reachability + schema/choice compatibility verified against running ComfyUI `0.46.0` Apple M1 MPS; does not certify `F05`/`F06` SDXL texture quality or `E3` visual acceptance)

## Code fix discovered during live ComfyUI 0.46.0 probing

ComfyUI `0.46.0` v3 nodes (such as `UpscaleModelLoader.model_name`) serialize combo inputs in `/object_info` using `["COMBO", {"multiselect": False, "options": [...]}]` rather than legacy `[[...], {...}]`. Both `validate_workflow` (`fidelis/studio/comfy.py`) and `inspect_workflow_bundle` (`fidelis/studio/worker_preflight.py`) now share `extract_field_choices` so legacy lists and v3 `COMBO` option lists are both checked for installed model availability and fail closed on missing choices.

## Live worker preflight evidence (`http://127.0.0.1:8188`)

Executed `scripts/backend-doctor.py` and `scripts/worker-preflight.py --require-qualified` against live `ComfyUI 0.46.0` (PyTorch `2.15.0`, `mps`, `8192 MB` unified RAM, `1088` installed node classes, `object_info_sha256: f1a1b6447b0eea0eeeea8501670345cb8cc6285d5ea9500bae23d82e8e4445e7`) with a same-grid `realesr-general-x4v3.pth` workflow (`workflow_sha256: 9c8d1bd1a2b9aaa35175c8cc8bb2e4c880241ad292f29a5e248c71aea5cf784d`):

- **Policy**: `config/worker-preflight-policy-v1.json` (`policy_sha256: 0399580a395e4f560f09bebee6f4bdf48cebce67abfd2038b84ce98c5dabe5ec`, `owner: local-operator`, `access_method: loopback`, `allow_remote_cloud_fallback: false`, `max_paid_spend_usd: 0.0`, `policy_compliant: true`, `0` secret violations).
- **Positive preflight**: `preflight_status: "qualified_preflight"`, `schema_compatible: true`, `model_choice_checks` confirmed `UpscaleModelLoader.model_name = "realesr-general-x4v3.pth"` (`available: true`, `installed_choice_count: 1`) and `ImageScaleBy.upscale_method = "area"` (`available: true`, `installed_choice_count: 5`).
- **Negative fail-closed live check**: Replacing `model_name` with `"missing_nonexistent_upscaler.pth"` against the live worker returned `preflight_status: "workflow_incompatible"`, `schema_compatible: false`, `validation_error: "Installed model/choice unavailable for 2.model_name"`.
- **Private receipt**: Stored off-repo at `/Users/tyf12/melato-corpus/fidelis/release-evidence/f0b1ed2/f05a-live-preflight/worker-preflight-receipt.json` alongside `backend-doctor.json` and `workflow.json`.

## Remaining parent gates

- `F05` (`MEL-58`) and `F06` (`MEL-60`) remain `In Progress`: ComfyUI SDXL/Clarity-style checkpoint weights are not installed (`models/checkpoints/` empty), and full 60-case corpus / `E3` visual fidelity acceptance remains open.
