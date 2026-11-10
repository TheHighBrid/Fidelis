# Fidelis Studio task ledger

Updated 2026-11-10. Implementation checkpoint, not a release ledger. F01-F04
are implemented on the Studio branch and are In Review in Linear while PR #12
remains open. Read [current status](project/STATUS.md) and the [roadmap](project/ROADMAP.md)
for takeover and milestone acceptance. Canonical scope and task definitions:
[execution plan](FIDELIS_STUDIO_PLAN.md).

## Current milestone

M0 foundation and F04 persistent artifacts implemented. F08 brush/review controls
are implemented at `/regions`; visual/device validation
is still outstanding. The local ComfyUI adapter is protocol-tested but no live GPU
inference or automatic segmentation is claimed. Existing inference routes remain intact.

| Task | Status | Evidence / next deliverable |
| --- | --- | --- |
| F01 Audit and publish plan | Complete | `FIDELIS_STUDIO_PLAN.md`, baseline `0f10ca6`, primary references and corrected claims |
| F02 Region compositor | Complete | `fidelis/postprocess/regions.py`; explicit confidence, normalized overlap, linear-light blending, exact locks |
| F03 File reblend and recipe | Complete | `scripts/reblend-regions.py`; verified PNG export, hashes and unsigned recipe; `REGION_REBLEND.md` |
| F04 Artifact contracts and budget storage | Complete | SQLite versioned manifests, immutable checksummed disk artifacts, byte caps, stripe composition, restart/conflict/failure tests |
| F05 Runtime/model registry audition | In progress | `backend-doctor.py` audits checksums/runtime presence; candidates are absent here, so model audition remains pending |
| F06 Pinned generation adapter | In progress | Local ComfyUI adapter and job/CLI integration implemented; HTTP protocol tests pass; live exported workflow/model validation still required |
| F07 Durable queue and reconciliation | In progress | Generation run ledger, timeout resume and uncertain-submission reconciliation implemented; async worker/cancellation remain |
| F08 Region brush and reblend UI | In progress | Protect/skin/hair/fabric painting, erase, undo/redo, preview zoom, revision saves implemented; browser visual/device acceptance remains |
| F09 Segmentation audition | Planned | License clearance and annotated boundary evaluation |
| F10 Structural ROI protection | Planned | Explicit logo/seam/hardware masks and drift screening |
| F11 Colour-managed export | Planned | Alpha, ICC, precision path, export round-trip tests |
| F12 Corpus and comparator tooling | Planned | 60 licensed/consented cases, frozen 30/30 split |
| F13 Calibration and blind acceptance | Planned | Actual Clarity/Krea comparisons and category defect report |
| F14 Batch resilience | Planned | Bounded scheduling and resumable manifests |
| F15 UI polish and packaging | Planned | Real device, accessibility, upgrade and rollback evidence |
| F16 Production release | Planned | Quality and operational gates pass before parity claim |
| F17 Optional challengers | Deferred | Separate FLUX/SUPIR/self-hosted adapter after core release |

## Verification completed

Environment: Linux x86_64, Python 3.12 project `.venv`, NumPy 2.3.5,
OpenCV headless 5.0.0.93. No model weights or paid cloud inference used.

- `.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v`:
  **62 passed**, covering compositor/CLI, persistent job storage, concurrent revision
  conflict, failed-render rollback, schema/checksum/budget validation, HTTP import/
  reopen/reblend/export, request isolation, malformed mask headers, existing tilers
  and optional face-detector regressions. New tests also cover brush persistence and
  browser/native raster parity, runtime integrity inventory, ComfyUI HTTP protocol
  state handling and CLI cache reuse. Fixtures do not provide GPU quality evidence.
- `PATH="$PWD/.venv/bin:$PATH" bash tests/smoke-test.sh`: passed.
- Existing `tests/test-web-ui.sh` HTTP inference integration: passed.
- Regional UI and standalone editor JavaScript `node --check`: passed.
- `git diff --check`: passed.
- New regional tests added to the existing Linux/macOS GitHub Actions matrix.
  Remote CI result is separate from these local results.

The new tests verify routing and exact pixel preservation, not realistic texture
generation. No benchmark preference, M1/Android latency, or commercial parity
results have been measured in this batch. The persistent store now composes disk mappings in bounded stripes and streams PNG
export, but total-process memory including import decoding is not certified for
8K on the M1. Inputs remain untagged 8-bit sRGB RGB PNGs with imported or painted masks.
Browser visual review was blocked by the browser-to-local-server connection; HTTP
flow and JavaScript syntax verification succeeded. See `REGIONAL_WORKSPACE.md`.

## Next execution batch

F05/F06: obtain a real GPU worker with an exported, compatible model workflow,
verify installed model bytes/revisions and execute the golden-image audition.
Complete browser/device acceptance for F08, then add F07 asynchronous execution
and cancellation. Mask painting no longer requires an externally prepared NPZ. Real competitor
outputs and production
benchmark selection remain later evidence checkpoints. No paid calls or model
quality certification were part of this batch. The current executor has no PyTorch,
NVIDIA tooling, NCNN runtime/candidate weights, ComfyUI worker or cloud keys. See
`COMFY_TEXTURE_BACKEND.md` for the adapter contract and readiness evidence.

## Pipeline integrity supplement · 2026-11-10

D01-D04 are implemented with 77 passing Python tests and the existing shell checks,
awaiting PR #12 review/merge. See the [delivery receipt](project/checkpoints/2026-11-10-pipeline-integrity.md)
for exact scope, fixtures, nullable metrics and unsigned provenance. Earlier 62-test
counts above describe their historical snapshot. Next: scoped F07-A/F08-A work;
worker/model and device acceptance remain open.

## Background generation delivery · 2026-11-10

F07-A adds the opt-in durable queue, editor generation/status controls, scoped local
cancellation and explicit same-run recovery. **92 Python tests pass**; fixtures do
not certify live model quality. Pending review/merge in PR #12. See the
[async checkpoint](project/checkpoints/2026-11-10-async-generation.md) for evidence, resource limits and recovery boundaries.
Next implementation: F08-A native-pixel inspection. Live worker, device acceptance
and aggregate generated-cache retention remain open.

## Native inspection delivery · 2026-11-10

F08-A adds read-only, same-grid native crops with 100/200% CSS-pixel comparison,
revision pinning and stale-load protection. **102 Python tests pass**, including
Node geometry/DOM contracts; real browser/touch visual acceptance is separate.
Pending PR #12 review/merge. See the [native inspection receipt](project/checkpoints/2026-11-10-native-inspection.md).
Next: F08-B browser/device acceptance and F12-A corpus/ROI preparation. Live model
quality, confidence masks and resource/release gates remain open.

## Corpus inventory delivery · 2026-11-10

F12-A now has versioned protocol/slot design, rights/hash/group/ROI inventory and
local audit/freeze/verify tooling. **114 Python tests pass.** Actual audit: eight
regression assets, zero production-eligible cases and 60 unfilled slots. F12-A
remains In Progress; the production corpus is not frozen. See the
[corpus checkpoint](project/checkpoints/2026-11-10-corpus-inventory.md). Next: real corpus/permission/ROI review before tuning;
confidence-mask interfaces and browser/device review can proceed independently.

## Mask suggestion interface · 2026-11-10

F09 adds source-bound imported probabilities, confidence/ambiguity gating, persisted
preview and explicit accept/discard. Acceptance fills only untouched areas and
preserves manual masks/protection. **125 Python tests pass.** F09 remains partial;
no automatic segmentation model is configured or quality-qualified. See the
[mask suggestion checkpoint](project/checkpoints/2026-11-10-mask-suggestions.md). Next: actual model/label/terms and ROI
qualification, with browser/device and production corpus gates still open.

## Comparator runners & blind scoring groundwork · 2026-11-10

F12 / MEL-63 on isolated branch `work/mel-63-comparator-runners` adds
`fidelis/eval/comparators.py`, CLI `scripts/run-comparators.py`, and
`docs/COMPARATOR_RUNNERS.md`. Separate single-image comparator outputs, remote
permission enforcement, explicit unavailable results, dimension checks, and
blind A/B bootstrap CI scoring pass **129 Python tests** on synthetic locks and
regression assets; live comparators and cleared 60-case photos remain open. See the
[comparator checkpoint](project/checkpoints/2026-11-10-comparator-runners.md).
