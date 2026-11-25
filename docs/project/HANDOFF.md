# Fresh-context handoff

## Native-grid evaluation memory · 2026-11-25 · #129

The [memory checkpoint](checkpoints/2026-11-25-evaluation-memory.md) records a
disk-backed full-grid spectral path, bit-identical chunked luminance and reduced
F2/F3 temporary arrays. Actual M1 operation probes reduced spectral peak RSS
from 484,360,192 to 129,286,144 bytes at 2048×3072. Retained guarded zipper
pixels were evaluated at 4264×6400 in 7.127 s / 1,516,470,272 bytes peak RSS;
this is a resource probe of identical protected pixels, not a new model pass.
Original raw model failures remain. #129 is partial: bound remaining material,
drift and composition buffers before retrying the full 198.7MP twill target.

## Diagnostic receipt correction · 2026-11-25 · #127

`scripts/audition-melato.py --evaluate-acceptance` now saves
`audition_receipt.json` with actual protocol/manifest hashes, available checkpoint
hash, Python version and code identity. A dirty checkout or source archive without
Git cannot claim an exact commit. Diagnostic manifests are not corpus locks, and
this command cannot claim a frozen calibration recipe. Older summaries containing
`audition-melato-local`, `unfrozen-melato-audition`, `melato-protocol-v1` or weight
hash `local` contain placeholders; their `receipt.complete: true` is invalid.
Retain their image/metric evidence, but regenerate receipt/acceptance metadata
before using them for release qualification. No quantitative criterion changed.

## Specialty material eligibility audit & corpus fills · 2026-11-25

Treat **43/60** fixed slots as available (`calibration 22/30`, `held_out 21/30`)
after the material eligibility and construction-fit audits (#122 `46/60` ->
`43/60`, #123 `43/60` -> `41/60`), PR #124 (`tex_held_jacquard_brocade`,
`CH 18766647-30`, Public-Domain Cooper Hewitt tonal floral silk jacquard,
`3774×4096`), and verification of `tex_cotton_twill_chino` (Wikimedia Commons
`Chino_pants_close-up_-_DSC02850.JPG`, `CC0-1.0`, `4351×2854`, visually
inspected sand-dyed 2/1 cotton twill weave macro). All five separated candidate
review records remain preserved in `experiments/corpus_material_candidate_reviews.json`;
the remaining `17` unfilled slots stay missing until exact-subject/model-released
sources are verified. Do not weaken fiber, construction, colour or split
requirements to fill a slot.

## Active v1 evidence recovery · 2026-11-24

Execution remains authorized; creative and production approval remain pending.
The package manifest identifies `86c4f86d` with `merged_to_main: true`, retaining
the redistribution-cleared archives from #115/#116. Newer engineering work
includes #128 (`83f739a`) and the memory checkpoint above; these archives do not
include newer code. Rebuild against the eventual frozen release candidate and
verify its hashes, rather than labelling historical packages current.
The approved 97 Melato masters have an existing rights receipt in
`docs/CORPUS_ACQUISITION_PROPOSAL.md`; recover exact bytes by manifest hashes
from connected Drive rather than requesting renewed rights approval. Local
inventory currently has 34 unique images and eight inventory SHA matches.
The remaining specialty slots require material/ROI suitability review.

Official ComfyUI was exercised in isolated temporary environments; recorded M1
MPS inference/preflight and async receipts remain historical device evidence.
The temporary environments were subsequently lost. On 2026-11-25 the local
8188/8189 probes both failed to connect; this is current worker health, not a
retraction of earlier inference. Torch/Spandrel and pinned local weights are
available in the durable release-agent checkout. Restore a local worker from
the recorded tooling when needed; worker setup is independent engineering work,
not an owner-access requirement.

Current signoff policy permits the same person to fill creative-owner and
release-owner roles; neither final approval has been supplied. Independent F13
blind reviewers remain separately required. Existing M1 latency/RSS, composition,
and rollback evidence remains reusable within its recorded model/device scope.

Use this page when another human or AI takes over without the conversation.

## Mission

Natural fashion/product restoration with exact region protection and believable
photographic detail. Target: controlled Clarity-style generation plus the requested
Krea-style editable region workflow. Competitive parity is not established.

## Locate the actual work

- Repository: https://github.com/TheHighBrid/Fidelis
- Current Studio code: integrated into `main` through [PR #82](https://github.com/TheHighBrid/Fidelis/pull/82), merge `7310aa6` (2026-11-20). Latest inspected `main` is `127385d` (2026-11-23 19:58 ET, PR #98). Check newer commits before working.
- Audited baseline `0f10ca6` and PR #12 are historical references, not the current checkout. PR #12 is merged via #82; it is not pending. No release or quality acceptance is implied.
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
and network-bind findings. The fixture-tested implementations from PR #12 are on
`main` via #82; that is not a release. See the latest receipts below. The
[backlog snapshot](backlog.json) maps actual Linear links.

## Latest pipeline integrity delivery

D01-D04 are implemented and fixture-tested; this 2026-11-10 receipt predates the #82 merge of PR #12. The latest full Python run passed **77 tests**. See the
[2026-11-10 integrity receipt](checkpoints/2026-11-10-pipeline-integrity.md)
for changes, compatibility requirements, verification and remaining live gates.
Next independent work: F07-A asynchronous execution and F08-A native crop inspection.

## Background generation delivery · 2026-11-10

F07-A adds the opt-in durable queue, editor generation/status controls, scoped local
cancellation and explicit same-run recovery. **92 Python tests pass**; fixtures do
not certify live model quality. This 2026-11-10 receipt predates the #82 merge of PR #12. See the
[async checkpoint](checkpoints/2026-11-10-async-generation.md) for evidence, resource limits and recovery boundaries.
Next implementation: F08-A native-pixel inspection. Live worker, device acceptance
and aggregate generated-cache retention remain open.

## Native inspection delivery · 2026-11-10

F08-A adds read-only, same-grid native crops with 100/200% CSS-pixel comparison,
revision pinning and stale-load protection. **102 Python tests pass**, including
Node geometry/DOM contracts; real browser/touch visual acceptance is separate.
This 2026-11-10 receipt predates the #82 merge of PR #12. See the [native inspection receipt](checkpoints/2026-11-10-native-inspection.md).
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
4. Owner release signoff (`F16`); PR #82 integration is merged, not released.

## Studio review UI polish · 2026-11-19

A scoped branch `work/bot06-studio-ui-krea-polish-20261119` adds display-only mask
channel controls and native-inspector docking/nudging/readout on top of
`feat/region-aware-studio` at `26d80750`. It does not rewrite that branch.
**263 Python tests passed** in 59.962s after installing the missing pytest
importer; web UI, smoke and JavaScript syntax checks passed. Headless Chrome
157.0.8103.50 on Linux exercised a synthetic pair. This is not device or visual
acceptance. See [the receipt](checkpoints/2026-11-19-studio-ui-krea-polish.md).
The same branch now places the canvas and mask legend before the import form at
widths through 780px. The repeated headless Chrome check passed at 390, 900 and
1440px with no horizontal overflow. Do not treat that as F08-B or F15 device signoff.

## Unified Studio & PR stack reconciliation · 2026-11-19

Branch `work/unified-studio-20261119` (stacked on `PR #64` @ `b031001`) unifies
PRs `#48`, `#61`/`#75`, `#65`, `#66`, `#67`, `#69`–`#73`, `#76`–`#81`, passing
**498 Python unit tests**, **140 E2E pytest tests**, Chrome CDP (`0` defects),
deterministic `v3.1.0` packaging, and Apple M1 `E2` zero-cost `RealeSR-general-v3`
qualification. See
[2026-11-19 unified integration checkpoint](checkpoints/2026-11-19-unified-studio-integration.md).

## Coordination refresh · 2026-11-24

Latest inspected `main` is `127385d`. After #82, `main` also has F16 dual-owner
declaration guards (#88–#90), protected-export/structure integrity (#83, #85,
#86, #92), F06 Comfy fail-closed protocol work (#93–#96), docs reconciliation
(#84, #91), and the isolated Context.dev research capture (#98). Fixture CI on
that SHA was green; that is not visual, GPU, device, or release acceptance.

A 2026-11-24 tree/diff audit of leftover open PRs versus `127385d`: #75, #66,
#67, and #81 are fully absorbed and safe to close; #58 and #87 have narrow
unique leftovers (executable mode on `scripts/check-studio-integration.py`, and
#87 also lists three test modules in CI that `main`'s curated workflow omits).
Do not merge dirty or obsolete-based PRs as if their work were missing. See
[STATUS.md](STATUS.md) for the verdict table.

Release gates still open: live ComfyUI GPU worker (E2 / F05-A / F06 / F07),
rights-cleared 60-case corpus (F12; 30/60 slots inventoried but not frozen),
30-case dual-reviewer blind signoff (F13), physical Android/iOS review
(F08-B / F15), owner F16 signoff (the #88–#90 guards are not a signoff),
segmentation/ICC/colour acceptance, and uncertified leftover Codacy findings
on those open PR tips. PR #82 integration is merged, not released.
