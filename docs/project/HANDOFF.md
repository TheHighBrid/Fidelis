# Fresh-context handoff

Use this page when another human or AI takes over without the conversation.

## Mission

Natural fashion/product restoration with exact region protection and believable
photographic detail. Target: controlled Clarity-style generation plus the requested
Krea-style editable region workflow. Competitive parity is not established.

## Locate the actual work

- Repository: https://github.com/TheHighBrid/Fidelis
- Current Studio code: `feat/region-aware-studio`, open PR #12; latest delivery receipts below.
- Audited main baseline: `0f10ca6`; newer documentation does not imply Studio merged.
- Execution board: https://linear.app/melato/project/fidelis-studio-a057f366fa71
- Umbrella: GitHub #11 / Linear MEL-53. Stable plan IDs: F01-F17.

## Read and act

1. `AGENTS.md`, `ONBOARDING.md`, `STATUS.md` and `RISKS.md` in this documentation set.
2. Check `git status`, current branch, latest PR and relevant Linear dependencies.
3. Claim one bounded deliverable; record owner, files/interfaces and acceptance.
4. Reuse contracts and tests. Do not restart a framework/model-selection project.
5. Return a checkpoint receipt with SHA, actual results, limits and next action.

## Achieved and remaining

F01-F04 implementation exists: plan, compositor/CLI, persisted artifacts and budgets.
F05-F08 are partial: capability inventory, local Comfy transport/CLI, run identity,
mask painting/erase/undo and review. The local snapshot had 62 Python tests passing,
plus web UI integration/smoke/JS checks. That is fixture/protocol evidence.

Missing: actual selected weights and live worker output, live queue/cancellation
qualification, visual/device acceptance, automatic segmentation,
structural detection, managed colour/alpha/precision export, full corpus/comparator
quality acceptance, robust batches and release packaging/signoff.

Audited executor: no PyTorch, native candidate/runtime, NVIDIA tooling, reachable
ComfyUI worker or configured cloud keys. This does not describe the owner's device.
Do not ask the owner to retry known failed model experiments. Finish independent
engineering/evidence preparation and record precise unavailable access if needed.

## Do not regress

Unknown regions stay base; explicit protection wins. No silent resizing to align
outputs, no silent remote upload/retry, no invented model/LoRA, no default grain or
beauty smoothing, no fake LPIPS/C2PA/performance/quality claim. Retain the rejected
Nomos and source-fusion history. One full-resolution output per file.

## Current review work

Read the risk register for the legacy large-input import, provenance, metric-label
and network-bind findings. These inherited findings now have a fixture-tested
implementation in PR #12, pending review/merge; see the latest receipt below. The [backlog snapshot](backlog.json) maps actual Linear links.

## Latest pipeline integrity delivery

D01-D04 are implemented and fixture-tested on the Studio branch, pending PR #12
review/merge. The latest full Python run passed **77 tests**. See the
[2026-11-10 integrity receipt](checkpoints/2026-11-10-pipeline-integrity.md)
for changes, compatibility requirements, verification and remaining live gates.
Next independent work: F07-A asynchronous execution and F08-A native crop inspection.

## Background generation delivery · 2026-11-10

F07-A adds the opt-in durable queue, editor generation/status controls, scoped local
cancellation and explicit same-run recovery. **92 Python tests pass**; fixtures do
not certify live model quality. Pending review/merge in PR #12. See the
[async checkpoint](checkpoints/2026-11-10-async-generation.md) for evidence, resource limits and recovery boundaries.
Next implementation: F08-A native-pixel inspection. Live worker, device acceptance
and aggregate generated-cache retention remain open.

## Native inspection delivery · 2026-11-10

F08-A adds read-only, same-grid native crops with 100/200% CSS-pixel comparison,
revision pinning and stale-load protection. **102 Python tests pass**, including
Node geometry/DOM contracts; real browser/touch visual acceptance is separate.
Pending PR #12 review/merge. See the [native inspection receipt](checkpoints/2026-11-10-native-inspection.md).
Next: F08-B browser/device acceptance and F12-A corpus/ROI preparation. Live model
quality, confidence masks and resource/release gates remain open.

## Corpus inventory delivery · 2026-11-10

F12-A now has versioned protocol/slot design, rights/hash/group/ROI inventory and
local audit/freeze/verify tooling. **114 Python tests pass.** Actual audit: eight
regression assets, zero production-eligible cases and 60 unfilled slots. F12-A
remains In Progress; the production corpus is not frozen. See the
[corpus checkpoint](checkpoints/2026-11-10-corpus-inventory.md). Next: real corpus/permission/ROI review before tuning;
confidence-mask interfaces and browser/device review can proceed independently.

## Mask suggestion interface · 2026-11-10

F09 adds source-bound imported probabilities, confidence/ambiguity gating, persisted
preview and explicit accept/discard. Acceptance fills only untouched areas and
preserves manual masks/protection. **125 Python tests pass.** F09 remains partial;
no automatic segmentation model is configured or quality-qualified. See the
[mask suggestion checkpoint](checkpoints/2026-11-10-mask-suggestions.md). Next: actual model/label/terms and ROI
qualification, with browser/device and production corpus gates still open.

## Local SegFormer B0 audition · 2026-11-10

F09 now has a pinned optional CPU runner and one live photo smoke test.
The candidate proposed texture on patch and zipper ROIs. A manual patch lock
preserved every locked pixel. Commercial rights, wider ROI accuracy and
target-device performance remain open. See the [audition](../SEGFORMER_B0_AUDITION.md).

## Structural ROI locks and screening · 2026-11-12

F10 now supports revision-bound rectangle locks and read-only structural reports.
The CPU photo replay preserved all 6,461 locked patch and zipper pixels exactly.
Every pixel outside the locks matched the prior master. Automatic detail detection
and production-corpus validation remain open. See [structural ROIs](../STRUCTURAL_ROIS.md).

## Master export and batch delivery · 2026-11-13

The [export checkpoint](checkpoints/2026-11-13-export-and-review.md) covers
RGB16/alpha CLI reblending, saved batch export and the PR review fixes.
F11 and F14 remain in progress for browser and live-worker acceptance.

Studio now also offers a 16-bit download from a saved revision. It recomputes
the linear-light blend directly from the stored passes and masks in bounded
stripes. See [master export](../STUDIO_EXPORT.md). Managed browser ingest and
target-device colour acceptance remain open.

## Unified M1–M4 implementation, PR #12 hardening & Apple M1 audition · 2026-11-13

All M1–M4 engineering deliverables (`F05-A`, `F05-B`, `F08-B`, `F10`, `F11`, `F12`, `F13`, `F14`, `F15`, `F16`) are now integrated directly on `feat/region-aware-studio` (PR #12) with **189 passing Python unit tests**, zero-defect Chrome CDP browser acceptance (`tests/test-browser-acceptance.sh`), PR #12 review fixes (`16-bit PNG IHDR` guard, lazy `cv2` import, dimension-aware `run_id`), target-device Apple M1 (8 GB) Vulkan NCNN precision-base audition + 4.2 MP (`2048×2048`) end-to-end Studio pipeline evidence (`docs/APPLE_M1_PRECISION_BASE_AUDITION.md`), target-device Apple M1 (8 GB) SegFormer B0 segmentation latency/RSS evidence (`docs/SEGFORMER_B0_AUDITION.md`), and tracked `v3.1.0` release candidate manifest (`config/release-candidate-v1.json`).

Do **not** re-implement `F05-A`, `F05-B`, `F08-B`, `F10`, `F11`, `F12`, `F13`, `F14`, `F15`, or `F16` from scratch; their modules, CLIs, tests, and docs are already tracked on `feat/region-aware-studio`. Remaining work is strictly external `E2..E4` execution once external assets/workers are provisioned:
1. Live ComfyUI GPU worker preflight & texture workflow qualification (`F05-A`/`F06`/`F07`).
2. Rights-cleared 60-case photographic corpus population (`F12-A`) and live comparator runs (`F12`).
3. Dual-reviewer blind held-out quality signoff (`F13`) and physical Android/iOS touch review (`F08-B`/`F15`).
4. PR #12 merge and owner release signoff (`F16`).
