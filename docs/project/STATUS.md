# Current progress and evidence checkpoint

> **Current coordination update (2026-11-24, telemetry & backlog reconciliation):** PR #101 (`F10 / MEL-64` bounded-stripe structural ROI candidate proposal API/CLI) merged into `main` at `5cf8cb1`. `tests/test-pipeline-instrumentation.sh` now verifies both live local `127.0.0.1` companion telemetry ingestion and non-blocking offline fallback (`telemetry_posted=False`, `status="unreachable"`). `docs/project/backlog.json` is reconciled with `main` (`5cf8cb1`) and Linear `P-MEL-3` (`F01`–`F04`, `F05-B`, `F07-A`, `F07-B`, `F08-A`, `F08-B`, `F09`, `F11`, `F14`, `F15`, `F17`, and `D01`–`D04` marked `Done`). This remains an engineering integration, **not a release**, not deployment, and not visual or model-quality acceptance.

> **Current coordination update (2026-11-24, F10 / MEL-64 autonomous resume):** PR #101 merged bounded-stripe structural ROI candidate proposal (`propose_regions` in `fidelis/studio/structure.py`, `JobStore.propose_structure`, `POST /api/regions/jobs/<id>/propose-structure`, and `scripts/structural-roi.py propose`) into `main` at `5cf8cb1`. This remains an engineering integration, **not a release**, not deployment, and not visual or model-quality acceptance.

> **Current coordination update (2026-11-24):** The latest inspected `main` commit is `127385d` (`127385daae5f44d310e2d6d8c8bcc6f2587686a5`, committed 2026-11-23 19:58 ET) after PR #98. This remains an engineering integration, **not a release**, not deployment, and not visual or model-quality acceptance. Historical branch and test-count records below are provenance only; they must not be used as present-tense merge, CI, deployment or acceptance claims. Dated sections that still say “pending PR #12” are historical receipts; #12 is not pending. Confirm live branch/PR state before starting overlapping work.

> **Current integration checkpoint (2026-11-20):** Unified Studio PR #82 merged into `main` at `7310aa6`. This is an engineering integration, **not a release**, not deployment, or visual/model-quality acceptance. Start new work from the latest `main`; open PRs remain independent review work. Historical snapshots and branch-specific evidence below are retained for provenance and must not be interpreted as current branch instructions.

Snapshot date: 2026-11-10. Latest delivery base: `e0a8602`; native-inspection delivery is the commit containing its receipt below. Original Studio snapshot: `5f32fba`.
The 2026-11-10 date applies to those historical receipts, not to the coordination banner above. This page is a committed checkpoint, not a live status feed.

## Live main as of 2026-11-24

Latest inspected `main` is `127385daae5f44d310e2d6d8c8bcc6f2587686a5`. First-parent history after the #82 Studio merge (`7310aa6`, 2026-11-20) includes:

- F16 release-declaration guards: #88 fail-closed offline manifest preflight, #89 hardened quality digest and explicit dual-owner release signoff, #90 fail-closed on truthy non-boolean declarations. These are engineering checks, not a completed owner signoff.
- Protected-export and structure integrity: #83 transparency/orientation/colour metadata, #85 animated PNG import rejection, #86 source-grid and stripe-screening validation, #92 RGB16 IHDR fail-closed.
- F06 ComfyUI protocol fail-closed work: #93 boolean output indices, #94 linked output-index validation, #95 malformed prompt acknowledgement reconciliation, #96 malformed reconciliation payloads.
- Docs: #84 contributor entrypoints, #91 blueprint/roadmap reconciliation.
- #98 isolated Context.dev research capture (issue #97).

PR #12 merged via unified PR #82. Product-edge work from PR #14 landed through #64 and #82; #14 itself was closed unmerged. Do not treat #12 or #14 as pending merges.

Latest `main` push CI on `127385d`: Fidelis CI run [45301452853](https://github.com/TheHighBrid/Fidelis/actions/runs/45301452853) success (`shell-and-sweep-tests` on ubuntu-latest and macos-latest) and report-integrity run [45301453130](https://github.com/TheHighBrid/Fidelis/actions/runs/45301453130) success. That is fixture CI, not visual, GPU, device, or release acceptance. Codacy did not run on that `main` push.

### Open pull requests (tree/diff audit vs `127385d`, 2026-11-24)

Do not merge these leftover PRs as if the work were missing from `main`. Several are dirty or still targeted at obsolete bases. Close or retarget only with owner approval.

| PR | Verdict | Notes |
| --- | --- | --- |
| #75 | Fully absorbed, safe to close | Head `9c53598` is an ancestor of `main` (ahead 0, 282 behind). |
| #66 | Fully absorbed, safe to close | Head `ec4adc5` is an ancestor of `main` (ahead 0, 184 behind). |
| #67 | Fully absorbed, safe to close | Head `36bd4e6` is an ancestor of `main` (ahead 0, 126 behind). |
| #81 | Fully absorbed, safe to close | Four unique commit SHAs remain, but file diffs vs `main` show no unabsorbed logic. `scripts/verify-protected-export.py` is a strict subset of `main`; CI and export tests on `main` already cover the intended guards. The tip is 287 commits behind. |
| #58 | Has unique changes; do not merge as-is | Only leftover vs `main` is executable mode `100755` on `scripts/check-studio-integration.py` (`main` is `100644` with identical later, stricter script content). Merging the PR would regress that script. |
| #87 | Has unique changes; do not merge the dirty PR | Unique leftovers: (1) `.github/workflows/ci.yml` explicitly runs `test_studio_png_single_frame.py`, `test_structure_screen_contract.py`, and `test_current_main_handoff.py`, which exist on `main` but are absent from the curated workflow list; (2) the same executable-mode bit as #58. Other file diffs are stale or equivalent wording already superseded on `main` (#83–#86, #92, later STATUS banner). The PR is conflicted against current `main`. |

The #58/#87 executable-mode leftover and the three unlisted CI test modules are housekeeping items, not release gates, and are not claimed fixed here.

Leftover open-PR Codacy conclusions were not certified resolved on `main`: #66 tip `ec4adc5` action_required (12 new issues), #67 tip `36bd4e6` (10 new), #75 (1 new), #87 (1 new), #58 (1 new). #81's head was Codacy success. Codacy did not run on the `127385d` `main` push.

### Release gates still open

None of the following is accepted or certified by current `main` CI:

- E2: live ComfyUI GPU texture worker qualification (F05-A / F06 / F07), including live queue/cancellation against a real worker.
- F12 / F12-A: rights-cleared 60-case photographic corpus is not frozen. The 2026-11-19 unified checkpoint records 30/60 off-repo Melato slots inventoried, still pending `--master-root` byte verification and license clearance, with 30 slots still unfilled. Paid comparator runs are not done.
- F13: 30-case dual-reviewer blind held-out human signoff is not done.
- F08-B / F15: physical Android/iOS touch-device review is not done. Headless Chrome is not device signoff.
- F16: owner release signoff is not done. `main` has the dual-owner declaration guards from #88–#90; those guards are not themselves a signoff.
- Automatic segmentation / confidence-mask quality is not qualified; F09 remains partial.
- Automatic structural-detail detection and production-corpus validation remain open (bounded-stripe luminance-edge cluster proposal `scripts/structural-roi.py propose` / `POST /api/regions/jobs/<id>/propose-structure` is now implemented as a read-only contrast heuristic requiring explicit operator lock; semantic OCR/hardware recognition and 60-case corpus validation remain open).
- Managed ICC / alpha / precision export and target-device colour acceptance remain open.
- External hardware/access gates confirmed unavailable on the audited Apple M1 (`8 GB`) macOS host (`2026-11-24`): no reachable ComfyUI worker (`127.0.0.1:8188` `ConnectError`), no PyTorch (`torch_importable: false`), no NVIDIA GPU (`nvidia_smi_present: false`), no physical Android/iOS touch device (`adb not found`), no local off-repo 60-case Melato masters (stored off-repo on `/workspace/melato-corpus/fidelis`; only 34 subset/pool images are present locally under `~/melato-corpus/fidelis`), and no paid Clarity/Krea API budget/keys.

## Delivery reality

| Record | Verified state |
| --- | --- |
| Audited baseline code on main | Historical audit `0f10ca6`. Pre-Studio `main` at integration time was `1c954cd`. Studio landed via PR #82 at `7310aa6`. Latest inspected `main` is `127385d`. |
| Studio code | PR #12 and the product-edge work from PR #14 are on `main` through #64 and #82. This is not a release. Historical source heads were not rewritten. |
| Project coordination | Linear Fidelis Studio, P-MEL-3; existing umbrella MEL-53 linked to GH #11 |
| Product status | Engineering alpha; no GPU quality certificate or parity claim |
| Latest runtime work | D01-D04, F07-A and F08-A are on `main` via #82. Later integrity, F06, and F16 declaration guards are also on `main`. External acceptance gates remain open. |

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

F01-F04 implementation is on `main` via #82; Linear workflow labels may lag.
F05-F08 remain partial; the existence of these modules is not the final
one-click, automatically segmented, GPU-accepted product.

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

Remaining gates are strictly external `E2..E4` operational/human gates: live ComfyUI GPU texture worker (`F05-A`/`F06`/`F07`), 60-case licensed photographic corpus & paid comparator runs (`F12-A`/`F12`), 30-case blind human signoff (`F13`), physical Android/iOS touch hardware review (`F08-B`/`F15`), and owner release signoff (`F16`). PR #12 later landed on `main` via #82; it is not a remaining merge gate.

## F07-B generation cache budget · 2026-11-16

On the isolated MEL-82 branch, the local Comfy PNG cache now has an explicit
2048 MiB default payload cap, bounded atomic staging and same-run recovery after
quota rejection. Existing cached outputs and run identities are retained.
See [the checkpoint](checkpoints/2026-11-16-generation-cache-budget.md).
Operator-managed retention, complete filesystem/RSS measurement and live F07
acceptance remain open. This is a scoped change awaiting review, not a release.

## PR #12 review-remediation checkpoint · 2026-11-15

The Studio branch now includes five independently regression-tested corrections to the 2026-11-14 Codex review of PR #12: mandatory F13 comparator coverage (#17), fail-closed unknown-region fidelity (#18), separate audition image artifacts (#19), truthful Comfy weight/workflow provenance (#20), and actual generation SQLite backup schemas (#21). All five changes were merged into `feat/region-aware-studio` as squash commits; combined branch head after this delivery is `929334bed65de8db54e4a1bc6732f7176a91c5e6`. Each PR passed its Linux/macOS matrix and latest code review; focused integrated local tests passed **33 tests plus 4 subtests**. On 2026-11-15, the branch-head CI run [43673811216](https://github.com/TheHighBrid/Fidelis/actions/runs/43673811216) was independently checked through GitHub's run API and reported `completed` with conclusion `success` for that exact head SHA. This verifies the combined CI run; it does not merge, deploy, release or satisfy the remaining operational/human acceptance gates.

See [review remediation checkpoint](checkpoints/2026-11-15-pr12-review-remediation.md) for precise PR links, evidence scope and residual issues. The Docker Compose bridge-to-loopback transport defect remains open pending a security-preserving deployment test. No production promotion, paid comparator, live Comfy GPU acceptance or physical Android/iOS touch acceptance is claimed by these corrections.

## MEL-77 queue reliability handoff · 2026-11-19

Owner approved this run. Base is `f120f222f3b62890d17d760eb21a32294440fc0d` on `work/mel-77-registration-recovery-20261118` (draft PR #57). Delivery branch: `work/mel-77-ci-queue-bot03-20261119`. The commit that adds this note is the branch head. This is fixture/protocol evidence, not live GPU verification, merge, or release.

Claimed files:

- `fidelis/studio/generation.py`
- `tests/test_generation_queue.py`
- `fidelis/studio/packaging.py` (required archive path for `fidelis/studio/cancellation.py` only)
- `docs/ASYNC_GENERATION.md`
- `docs/project/STATUS.md`

`CancellationHandle` stays frozen. CI failure `test_retired_token_uses_durable_cancellation_before_result_apply` was reproduced locally on Python 3.12.3 as `dataclasses.FrozenInstanceError: cannot assign to field 'is_requested'` and then `cannot delete field 'is_requested'` from `patch.object(handle, 'is_requested', ...)`. The test now injects `PermissionError` through `CancellationSignals` and still requires a durable cancel to block an applicable receipt. A retired token with no durable flag does not cancel or block apply.

Queue hardening in the same module: SQLite writes use `BEGIN IMMEDIATE` and `synchronous=FULL`; a raised transaction does not publish the partial row; an empty, truncated, or non-SQLite `queue.sqlite3` raises `QueueStorageError` and is not rewritten; a readable database with a damaged task row is quarantined as `needs_review` (`quarantined`, `CorruptRecord`, SHA-256 of the rejected bytes) and is not executed or resumed until an explicit cancel; process restart marks valid `running`/`applying` rows `interrupted` and still runs untouched `queued` work; one in-flight claim and one worker thread are enforced; an unexpected worker exception marks the in-flight row `interrupted` and later tasks still run. No new ADR: the task table and single-owner boundary are unchanged.

Deliberately left out: `scripts/install-macos-runtime.sh` still downloads the native NCNN runtime and is not called by `scripts/package-offline-bundle.sh`; no WAL migration; no cross-database exactly-once apply reconciliation; no generated-cache quota; no edits to the region-aware studio UI or the codex product edge; no live Comfy worker run.

Local checks on this workspace, final tree:

- `unittest discover -s tests -p 'test_*.py'` without pytest: 314 results, 5 errors, all `tests/e2e/test_tier{1,2,3,4,5}_*.py` failing to import pytest. Those modules are pre-existing and are not in the CI per-file unittest steps. The other tests passed.
- Same discover after pytest was installed so those modules can import: **309 tests, OK, 71.646s**. Unittest does not execute the pytest functions.
- `tests/test-web-ui.sh`: `Web UI server tests passed.`
- `tests/smoke-test.sh`: `Static smoke tests passed.`
- `git diff --check`: clean.

GitHub Actions run [44510346371](https://github.com/TheHighBrid/Fidelis/actions/runs/44510346371) on `650e87442e764214c796195fb12366f1c6f636b7` completed with conclusion `success`. Both `shell-and-sweep-tests` jobs succeeded, and **Durable background generation and cancellation tests** succeeded on Ubuntu (10:57:54Z–10:58:21Z) and macOS (11:00:31Z–11:01:39Z). Codacy Static Code Analysis on that same SHA completed `action_required` (“3 new issues”). Live cancellation against a real ComfyUI worker remains a separate gate.

This branch then merges Bot01 tip `b03100192544024f56646c91ee560b8857de7e1c` (`origin/cursor/integrate-pr12-pr14-7a85`) with merge commit `15423b9f3ea9ba2b3ae28104dca64f6ce231ac51`. PR #12/#14 integration notes below stay. Queue behavior stays the MEL-77 record above.

Codacy on `650e874` reported three new medium issues in `fidelis/studio/generation.py`: two `type()` integer checks (lines 212 and 240) and one `try/except/pass` (line 557). The revision check now uses `isinstance` and still rejects booleans. A failed abandon write is recorded and retried instead of discarded. Local checks after that edit and the merge: `unittest discover` **371 tests, OK, 75.676s**; `tests/test-web-ui.sh` and `tests/smoke-test.sh` passed; `git diff --check` was clean. Remote CI and a cleared Codacy check for the new tip are separate evidence.

## F08-B browser gate integrity follow-up · 2026-11-16

The bounded MEL-80 follow-up makes acceptance reports and exit codes agree, verifies
the actual expected stale-save conflict, and bounds browser command failures. Eight
Node regression tests pass; Linux Chromium aborted before DevTools startup, so this
does not renew the historical macOS browser acceptance. See the
[gate integrity receipt](checkpoints/2026-11-16-browser-gate-integrity.md).

## PR #12 security and maintainability remediation · 2026-11-17

The scoped browser security follow-up [PR #38](https://github.com/TheHighBrid/Fidelis/pull/38)
passed Codacy and both GitHub workflows before integration into the Studio feature
branch, not `main`. The runner now publishes artifacts using descriptor-relative
atomic writes and transmits browser-derived values as CDP arguments instead of
interpolating executable expressions. Provenance, comparator execution, blind review,
held-out acceptance, and release readiness were decomposed into independently
testable stages without relaxing their evidence requirements. No live-worker,
physical-device, human visual, or release acceptance is implied by these changes.

## F10 / PR #14 product upscale review remediation · 2026-11-17

The opt-in product command now feathers inward from the union of permitted
texture ROIs while preserving every unknown and locked base pixel. It creates
missing output parent directories before staging, and rejects wrong-sized model
outputs without replacing a prior export. The inherited browser runner now
handles execution failures explicitly while retaining cleanup and a nonzero exit.
These changes are fixture/protocol evidence on the PR #14 branch, not photographic
acceptance or release. See [ROI protection](../ROI_DRIFT_SCREENING.md).

## Integration onto main · 2026-11-19

This branch starts at main `1c954cd5d3b949c124b467228669213a50d47355` and merges
PR #12 (`26d80750`) and then PR #14 (`62f55cb`). It does not merge those pull
requests, rewrite their heads, or claim visual, GPU, or release acceptance.

Conflict resolution, where the two histories disagreed:

- `.github/workflows/ci.yml`: both sides. Main's upload and interaction jobs stay, and the Studio suite stays, including the product-upscale job from PR #14. The main provenance, tiling, protected-export, Compose exposure, and color-routing tests are now explicit CI jobs.
- `fidelis/core/pipeline.py`: main's provenance module and hyphenated tiled entrypoint. PR #12's nullable metrics stay, and the selected CLI is passed to tiled upscale. PR #14's `run_native_pass` stays. A gradient value is not labelled LPIPS.
- `fidelis/eval/corpus.py`: main's aligned 4× synthetic pairs.
- `scripts/web-ui.py`: main's 32 MiB upload gate, image decode, and 16-megapixel limit, plus the regional routes. The server still defaults to `127.0.0.1`.

The unsigned sidecar keeps main's MEL-73 writer. Its media type is
`application/vnd.fidelis.provenance+json`. A successful write is `unsigned`; a
failed write is `write_failed`. The record also carries
`record_type: unsigned_execution_record` and `signature_info.signed: false`.
The 2026-11-10 pipeline-integrity receipt describes the earlier PR #12 writer,
including `application/json`. That receipt is not the current sidecar contract.
Nothing here is a verified C2PA manifest.

Local verification on this branch, Python 3.12 with the documented test
dependencies plus pytest so `tests/e2e` can import:

- `unittest discover -s tests -p 'test_*.py'`: 312 tests, OK. Without pytest the
  same command reported 5 e2e import errors. Discovery does not execute the
  pytest functions.
- `tests/test-web-ui.sh` and `tests/smoke-test.sh` passed.
- `node --check` passed for `fidelis/studio/editor.js`,
  `fidelis/studio/inspection.js`, `scripts/browser-acceptance.mjs`,
  `tests/native-inspection-ui.cjs`, and
  `tests/test_browser_acceptance_report.mjs`.
- `node --test` passed for `tests/test-studio-interactions.cjs` and
  `tests/test_browser_acceptance_report.mjs`. The native inspection fixture is
  executed by `tests/test_native_inspection.py`, which is inside the 312.
- `git diff --check` is recorded with the commit. No GPU, visual, or device
  acceptance is claimed. Remote CI is separate evidence.

The first macOS CI job failed in `test_oversized_request_rejected_before_read`
with `ConnectionResetError` while reading the 413 response. The handler now
sends that JSON error with `Content-Length` and discards at most 64 KiB of
bytes already buffered, so the socket can close. It still does not read the
declared oversized body. Local discovery after that change remained 312 tests,
OK. Ubuntu CI and the browser-report job had passed on the previous head.
Codacy on this draft is a separate finding and is not cleared here.

## Studio review UI polish · 2026-11-19

On `work/bot06-studio-ui-krea-polish-20261119`, based on `26d80750`, the regional
page now has display-only per-channel mask visibility, overlay strength, a
protection hatch, a docked or pinned native inspector, arrow-key crop nudging,
and a browser-decoded crop RGB readout. Preview zoom stays labelled as the
reduced overview. Blend saving and protection semantics are unchanged.

Local discovery passed **263 tests in 59.962s** after the executor's missing
`pytest` import was installed. The same command had first reported 268 tests and
5 E2E import errors. Web UI integration, static smoke, `git diff --check` and
the touched JavaScript syntax checks passed. Headless Chrome 157.0.8103.50 on
this Linux host exercised a synthetic 64×48 pair at 1440, 900 and 390px. A
follow-up on the same branch places the canvas and mask legend before the import
form at widths through 780px. The repeated headless check kept 390px in stack
order (canvas, then legend, then import) and kept 900px and 1440px as a left
rail plus canvas, with no horizontal overflow at those three widths. That is
not physical-device or human visual acceptance. See
[the receipt](checkpoints/2026-11-19-studio-ui-krea-polish.md).

## Unified Studio & PR stack reconciliation · 2026-11-19

On `work/unified-studio-20261119`, stacked cleanly onto `PR #64` (`b031001`), all
open M1–M4 engineering PRs (`#48`, `#61`/`#75`, `#65`, `#66`, `#67`, `#69`–`#73`,
`#76`, `#77`, `#78`, `#79`, `#80`, `#81`) are reconciled additively with
updated `REQUIRED_ARCHIVE_PATHS` and CI coverage. Local verification passes
**498 Python unit tests**, **140 E2E pytest scenarios**, `tests/smoke-test.sh`,
`tests/test-web-ui.sh`, `tests/test-release-pipeline.sh`,
`tests/test-browser-acceptance.sh` (Chrome 157.0.8103.79 CDP, `0` defects),
Node UI/interaction tests, `scripts/audit-model-provenance.py`, and zero-cost
`E2` `RealeSR-general-v3` M1 execution (`scripts/qualify-realesr-general-v3.py --record-live`).
See the [2026-11-19 unified integration checkpoint](checkpoints/2026-11-19-unified-studio-integration.md).
Remaining external gates: live GPU ComfyUI worker, off-repo 60-case licensed
corpus completion & dual-reviewer human signoff, physical touch-device QA, `main`
merge, and owner release signoff.
