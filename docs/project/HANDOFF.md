# Fresh-context handoff

Use this page when another human or AI takes over without the conversation.

## Mission

Natural fashion/product restoration with exact region protection and believable
photographic detail. Target: controlled Clarity-style generation plus the requested
Krea-style editable region workflow. Competitive parity is not established.

## Locate the actual work

- Repository: https://github.com/TheHighBrid/Fidelis
- Current Studio code: `feat/region-aware-studio`, `5f32fba`, open PR #12.
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

Missing: actual selected weights and live worker output, async queue/cancellation,
visual/device acceptance, native image-pixel inspection, automatic segmentation,
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
