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
| Latest runtime work | D01-D04, F07-A, F08-A, F09, F12-A and F13 held-out acceptance protocol implemented/tested; pending review/merge |

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

## Held-out quality acceptance protocol · 2026-11-10

F13 (`MEL-66`) adds `fidelis/eval/quality_acceptance.py` and
`scripts/evaluate-quality-acceptance.py` to enforce reproducibility receipts,
calibration/held-out split isolation, zero critical fidelity defects, Wilson and
bootstrap 95% CIs, per-target/per-category thresholds, and explicit owner signoff
gating. **129 Python tests pass.** F13 remains partial until the cleared 60-case
production corpus, live comparator outputs, human blind ballots, and owner creative
signoff are recorded. See the
[held-out acceptance checkpoint](checkpoints/2026-11-10-held-out-acceptance.md).
