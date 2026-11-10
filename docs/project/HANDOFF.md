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

## Same-host browser acceptance · 2026-11-10

F08-B / MEL-80 on isolated branch `work/mel-80-browser-acceptance` adds
`scripts/browser-acceptance.mjs` and `tests/test-browser-acceptance.sh` driving
live `Google Chrome 157.0.8103.50` (`darwin arm64`) over CDP against `/regions`.
Verified file import, mouse/touch painting, blur-safe `Ctrl+Z`, redo, save/reload,
native 100/200% inspection, `409` stale-edit preservation, and `390×844` mobile
overflow, logging 3 minor UI findings (`UX-KEYBOARD-FOCUS-TRAP`,
`MISSING-FAVICON-404`, `UX-DESKTOP-CANVAS-SCROLL`). F08-B is `In Progress`
(`partial`); physical touch devices and human visual review remain open. See
the [browser acceptance checkpoint](checkpoints/2026-11-10-browser-acceptance.md).
