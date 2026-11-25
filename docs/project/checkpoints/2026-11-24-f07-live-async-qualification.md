# F07 Live Studio Async Queue Qualification · 2026-11-24

- **Linear**: `MEL-61` (`F07 · Implement durable async jobs and scoped cancellation`)
- **Base SHA**: `d6f420ccf1754c79931c9822ec5127b98ab0df5c` (`origin/main`)
- **Qualification Harness**: `scripts/qualify-async-queue.py` (`tests/test_async_queue_qualification.py`)

## What Was Verified Live

Executed `scripts/qualify-async-queue.py` against live local `ComfyUI 0.46.0`
(`http://127.0.0.1:8188`, PyTorch `2.15.0` MPS on Apple M1) driving the actual
`scripts/web-ui.py --bind 127.0.0.1 --texture-workflow ...` Studio server over
loopback HTTP, using a `177×384` crop of `IMG_0932.jpg` (`source_sha256`:
`6a466d2f233f91fa2d0d2bf3e18a2879ba00d1066869d743350aae66a09df79f`) and a
same-grid `realesr-general-x4v3.pth` workflow bundle (`workflow_sha256`:
`9c8d1bd1a2b9aaa35175c8cc8bb2e4c880241ad292f29a5e248c71aea5cf784d`):

1. **Worker preflight (`F05-A` / `F07`)**: `qualified_preflight` (`schema_compatible: true`, loopback policy compliant, `$0.00` spend).
2. **HTTP responsiveness & exact protection**: `POST /api/regions/jobs/{id}/generations` returned `202`; active-run `GET /api/regions/jobs` polling stayed responsive (`max_http_poll_latency_ms: 14.18`); job advanced to `revision: 2` (`prompt_id: a48d16cb-6bc2-4f82-9ce1-0dd8df4564ad`) with `0` protected-pixel mismatches and `0` unknown-pixel mismatches.
3. **Scoped cancellation without global interruption**: Enqueued two distinct jobs (`1c3cb55f...` and `63b7ee7a...`), cancelled the first (`POST .../cancel` -> `status: cancelled`, `remote_may_continue: true`, `revision: 1`), and observed the unrelated peer job finish cleanly (`status: completed`, `prompt_id: 9e6aadc8-dcbb-4d2b-bc02-86023d00a1f6`, `0` protected/unknown pixel mismatches).
4. **Restart recovery & single-prompt reconciliation**: Terminated `scripts/web-ui.py` after `prompt_id` `676dbd2d-a087-48ca-b9ae-1bb5db730fa9` persisted in `generation.sqlite3`; restarted `scripts/web-ui.py` on the same workspace and generation root; confirmed task entered `interrupted` without auto-resubmission (`revision: 1`); called `POST .../resume` and confirmed completion on the **exact same `prompt_id`** (`single_prompt_id_preserved: true`, `0` protected/unknown pixel mismatches).

Private live receipt and artifacts are stored off-repo at
`/Users/tyf12/melato-corpus/fidelis/release-evidence/d6f420cc/f07-live-async/f07-live-receipt.json`.

## Remaining Open Gates

- **Live quality / SDXL (`F06` / `E3`)**: `live_quality_verified: false`, `e3_visual_accepted: false`. Same-grid `realesr-general-x4v3.pth` (`ImageUpscaleWithModel` + `0.25` area downsample) verifies operational queue/bridge behaviour, not SDXL/Clarity-style texture quality.
- **External `E2..E4` gates**: 60-case licensed corpus (`F12-A`/`F12`), blind held-out quality signoff (`F13`), physical Android/iOS touch QA (`F08`), and release packaging/owner signoff (`F16`) remain open.
