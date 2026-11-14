# Current progress and evidence checkpoint

Snapshot date: 2026-11-10. Latest delivery base: `e0a8602`; native-inspection delivery is the commit containing its receipt below. Original Studio snapshot: `5f32fba`.
This is a committed checkpoint, not a live status feed.

## Delivery reality

| Record | Verified state |
| --- | --- |
| Audited baseline code on main | `0f10ca6`; subsequent documentation publication does not merge Studio code |
| Studio code | `feat/region-aware-studio`, open PR #12; latest delivery receipts below |
| Project coordination | Linear Fidelis Studio, P-MEL-3; existing umbrella MEL-53 linked to GH #11 |
| Product status | Engineering alpha; no GPU quality certificate or parity claim |
| Latest runtime work | D01-D04, F07-A and F08-A implemented/tested in PR #12; pending review/merge |

## Implemented achievements

- F01-F04: corrected plan, tested linear-light compositor and CLI, exact protected
  pixels, persistent jobs/artifacts/revisions, storage limits and restart recovery.
- F05/F06: runtime/checksum inventory, exported-graph validation, local ComfyUI
  transport and CLI/job texture replacement with preserved masks.
- F07 groundwork: run/prompt identity, timeout resume, cache verification and
  uncertain-submission reconciliation without automatic duplicate generation.
- F08: optional imported masks, protect/skin/hair/fabric painting, erase,
  size/hardness/opacity, unsaved undo/redo, keyboard controls, preview zoom,
  revision reload, comparison and streaming full-resolution PNG export.

F01-F04 remain In Review rather than Done on the coordination board until delivery
is reviewed/merged. F05-F08 remain partial; the existence of these modules is not
the final one-click, automatically segmented, GPU-accepted product.

## Verification provenance

At the recorded Studio SHA, 62 local Python tests passed, plus existing web UI HTTP
integration, static smoke checks and JavaScript syntax. Coverage includes native/
browser brush math parity, persistence, revision/concurrency/rollback, malformed
uploads, Comfy HTTP protocol states and CLI cache reuse. The Comfy fixture deliberately
uses fixed pixels and a FixtureTexture node; it is not GPU inference evidence.
Remote CI, visual appearance and target-device evidence must be checked separately.
Historical checkpoint counts do not replace the latest delivery evidence below; none certifies model quality.

## What remains

Actual selected model/workflow output and compatibility; live qualification of async execution/cancellation; browser/device acceptance;
automatic confidence masks; logo/seam/hardware detection and internal drift checks;
managed ICC/alpha/precision export; rights-cleared corpus and Clarity/Krea held-out
comparisons; resumable Studio batches; production packaging and release signoff.

See [Roadmap](ROADMAP.md) for F01-F17 and [Risks](RISKS.md) for inherited defects.
The original detailed [task ledger](../FIDELIS_STUDIO_TASKS.md) remains a supporting
implementation checkpoint; this page is the concise takeover entry point.

## Current capability boundary

The audited development executor had no native candidate/runtime, PyTorch,
NVIDIA tooling, reachable ComfyUI worker or configured cloud keys. That is not a
claim about the owner's Mac/tablet or proof that every future executor lacks a GPU.
Previous browser review could not reach the local server; visual/device acceptance
is still open. Do not repeat the same failed connection or model experiment without
a material change in setup/evidence.

## Next work and checkpoint

Documentation/management setup is published. D01-D04 now have a regression-tested
implementation in the Studio branch. No new model or paid inference was started.
Contributors can independently prepare corpus/weight provenance and implement
scoped async work and native crop inspection. A real compatible worker/model is required
before F05/F06 live quality acceptance. Complete a checkpoint receipt for the next
actual code or quality change and update its existing Linear issue.

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

## Studio structural controls · 2026-11-13

The native inspector can check the displayed crop for pixel and strong-edge changes and commit a rectangular lock. It reloads the crop on the new revision. See [Studio crop locks](../STRUCTURAL_ROIS.md#lock-a-crop-in-studio).

## Master export and batch delivery · 2026-11-13

The [export checkpoint](checkpoints/2026-11-13-export-and-review.md) covers
RGB16/alpha CLI reblending, saved batch export and the PR review fixes.
F11 and F14 remain in progress for browser and live-worker acceptance.

Studio now also offers a 16-bit download from a saved revision. It recomputes
the linear-light blend directly from the stored passes and masks in bounded
stripes. See [master export](../STUDIO_EXPORT.md). Managed browser ingest and
target-device colour acceptance remain open.

## Saved batch precision and recovery · 2026-11-13

F14 / MEL-67 accepts per-item 8-bit or 16-bit PNG export from saved Studio
revisions. The resume receipt binds the requested bit depth and accepts older
8-bit receipts. Output budgets include interrupted staging and temporary
verification copies. Model-backed batch scheduling remains open.
See [master export](../STUDIO_EXPORT.md).

Verification: 144 Python tests, web HTTP integration and smoke tests passed.
A CLI replay from a persisted job created and reused a 16-bit PNG. Independent
review reproduced a temporary master mapping overlap and identified receipt
staging ahead of its byte check. Both now have regression coverage.

## Unified M1–M4 implementation, PR #12 hardening & Apple M1 audition · 2026-11-13

All M1–M4 engineering deliverables (`F05-A`, `F05-B`, `F08-B`, `F10`, `F11`, `F12`, `F13`, `F14`, `F15`, `F16`) are now unified on `feat/region-aware-studio` alongside `F09` (`SegFormer B0` smoke test) and `F10` (`fidelis/studio/structure.py` + Studio crop check/lock controls). **189 Python unit tests pass**, plus `tests/smoke-test.sh`, `tests/test-web-ui.sh`, `tests/test-release-pipeline.sh`, and `tests/test-browser-acceptance.sh` (`Google Chrome 157.0.8103.79` CDP on `darwin arm64` with `observed_defects: []`).

Target-device **Apple M1 (8 GB RAM) Vulkan NCNN precision-base audition** (`F05` / `MEL-58`) is recorded in [`docs/APPLE_M1_PRECISION_BASE_AUDITION.md`](../APPLE_M1_PRECISION_BASE_AUDITION.md) across `RealeSR-general-v3` (`70.9–104.6 MB` peak RSS, `1.35–1.80 s` on `512×512 -> 2048×2048`), `RealSR-DF2K` (`556.8–684.1 MB` peak RSS, `PSNR 34.70–37.41 dB`), and `ESRGAN-Remacri` (`407.7–415.1 MB` peak RSS, `98.93%–99.22%` gradient coherence) with `0.0 px` registration shift across all evaluated blocks and ROIs. Target-device **Apple M1 (8 GB RAM) SegFormer B0 segmentation benchmark** (`F09` / `MEL-62`, `onnxruntime 1.32.0`) is recorded in [`docs/SEGFORMER_B0_AUDITION.md`](../SEGFORMER_B0_AUDITION.md) (`0.44–0.83 s` total CLI + stripe upsample latency and `292.1–379.0 MB` peak RSS across `512×512` to `2048×2048` grids). An **end-to-end 4.2 MP (`2048×2048`) Apple M1 multi-pass Studio pipeline replay** (`RealeSR-general-v3` base + `ESRGAN-Remacri` texture pass + `SegFormer B0` proposal/accept + `F10` 4x patch/zipper locks preserving all `103,376` locked pixels bit-for-bit + `F11`/`F14` 16-bit/8-bit batch export + `F15` workspace snapshot/restore + `F16` release candidate manifest `config/release-candidate-v1.json`) is recorded in [`docs/APPLE_M1_PRECISION_BASE_AUDITION.md`](../APPLE_M1_PRECISION_BASE_AUDITION.md#6-end-to-end-42-mp-2048--2048-multi-pass-studio-pipeline-benchmark-on-apple-m1-8-gb) and [`docs/RELEASE_READINESS.md`](../RELEASE_READINESS.md).

Remaining gates are strictly external `E2..E4` operational/human gates: live ComfyUI GPU texture worker (`F05-A`/`F06`/`F07`), 60-case licensed photographic corpus & paid comparator runs (`F12-A`/`F12`), 30-case blind human signoff (`F13`), physical Android/iOS touch hardware review (`F08-B`/`F15`), PR #12 merge, and owner release signoff (`F16`).
