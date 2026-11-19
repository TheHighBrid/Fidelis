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
| F03 File reblend and recipe | Complete | `scripts/reblend-regions.py`; verified PNG export, hashes, 16-bit IHDR guard and unsigned recipe; `REGION_REBLEND.md` |
| F04 Artifact contracts and budget storage | Complete | SQLite versioned manifests, immutable checksummed disk artifacts, byte caps, stripe composition, restart/conflict/failure tests |
| F05 Runtime/model registry audition | In progress | `F05-B` provenance manifest (`config/model-provenance-v1.json`) + `F05-A` worker preflight (`scripts/worker-preflight.py`) + Apple M1 8GB NCNN Vulkan hardware audition (`docs/APPLE_M1_PRECISION_BASE_AUDITION.md`); 60-case corpus and commercial license clearance open |
| F06 Pinned generation adapter | In progress | Local ComfyUI adapter and job/CLI integration implemented (`fidelis/studio/comfy.py`); HTTP protocol tests + dimension-aware `run_id` pass; live exported workflow/model validation still required |
| F07 Durable queue and reconciliation | In progress | `F07-A` bounded async worker, scoped local cancellation, timeout resume and uncertain-submission reconciliation implemented (`fidelis/studio/generation.py`); live worker acceptance remains open |
| F08 Region brush and reblend UI | In progress | `F08-A` native 100/200% pixel inspector + `F08-B` same-host Chrome CDP acceptance (`scripts/browser-acceptance.mjs`, 0 defects across desktop 1440×900 & mobile touch 390×844); physical Android/iOS touch review remains open |
| F09 Segmentation audition | In progress | Source-bound imported probabilities + pinned `Xenova/segformer_b0_clothes` CPU smoke test (`docs/SEGFORMER_B0_AUDITION.md`); commercial terms, annotated ROI accuracy and target devices pending |
| F10 Structural ROI protection | In progress | Explicit revision-bound structural ROI locks + Studio crop check/lock UI (`fidelis/studio/structure.py`, `docs/STRUCTURAL_ROIS.md`) + phase-correlation/Sobel internal drift screening (`fidelis/postprocess/roi_protection.py`, `docs/ROI_DRIFT_SCREENING.md`); 60-case corpus validation open |
| F11 Colour-managed export | In review | ICC profile preservation (`sRGB`, `Display P3`, `Adobe RGB`), EXIF orientation normalization, straight-alpha composition and 8-bit/16-bit PNG/TIFF export (`fidelis/postprocess/managed_export.py`, `docs/MANAGED_EXPORT.md`) |
| F12 Corpus and comparator tooling | In progress | `F12-A` 60-slot schema/freeze auditor (`fidelis/eval/corpus_manifest.py`) + `F12` local NCNN/ComfyUI and opt-in Clarity/Krea comparator runner adapters (`fidelis/eval/comparators.py`, `docs/COMPARATOR_RUNNERS.md`); 60 licensed cases and live paid comparator runs pending |
| F13 Calibration and blind acceptance | In progress | Held-out quality acceptance evaluator (`fidelis/eval/quality_acceptance.py`, `docs/QUALITY_ACCEPTANCE.md`) with Wilson 95% CIs, Krippendorff's α / Cohen's κ and G1-G6 gates; live 30-case blind human signoff pending |
| F14 Batch resilience | In review | SQLite-backed resumable batch runner (`fidelis/studio/batch.py`, `docs/BATCH_PROCESSING.md`) with idempotent item keys, uncertain-submission reconciliation and rate-limit circuit breaker |
| F15 UI polish and packaging | In progress | Reproducible Studio source/offline tarballs, non-root `127.0.0.1` `Dockerfile`, upgrade/rollback verifier (`fidelis/studio/packaging.py`, `docs/RELEASE_PACKAGING.md`) and Chrome CDP UI polish fixes; physical Android device signoff pending |
| F16 Production release | In progress | Fail-closed `E1..E4` release readiness dossier auditor (`fidelis/studio/release_readiness.py`, `docs/RELEASE_READINESS.md`); remains blocked until PR #12 merges and external `E2..E4` gates + owner signoff close |
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

## Unified M1–M4 implementation, PR #12 hardening & Apple M1 audition · 2026-11-13

All remaining M1–M4 engineering deliverables (`F05-A`, `F05-B`, `F08-B`, `F10`, `F11`,
`F12`, `F13`, `F14`, `F15`, `F16`) have been integrated onto `feat/region-aware-studio`
alongside `F09` (`SegFormer B0` smoke test) and `F10` (`fidelis/studio/structure.py` +
Studio native-inspector crop check/lock controls):

- **Apple M1 (8 GB) Precision-Base Hardware Audition (`F05` / `MEL-58`)**: Executed real
  Vulkan NCNN inference across `RealeSR-general-v3`, `RealSR-DF2K`, and `ESRGAN-Remacri`
  on 4 photographic inputs (`astronaut_nasa_512`, `portrait_skin_real`,
  `fashion_fabric_real`, `product_edges_real`), recording runtime/weight SHA-256s,
  latency (`0.52–16.39 s`), `/usr/bin/time -l` peak RSS (`70.9–684.1 MB`),
  source-consistency metrics, and structural ROI screening (`0.0 px` registration shift).
  See [`docs/APPLE_M1_PRECISION_BASE_AUDITION.md`](APPLE_M1_PRECISION_BASE_AUDITION.md).
- **Same-Host Chromium CDP Acceptance (`F08-B` / `MEL-80`)**: Executed real headless
  Google Chrome (`157.0.8103.79` on `darwin arm64`) over CDP (`scripts/browser-acceptance.mjs`),
  resolved all 3 minor UI defects (`UX-KEYBOARD-FOCUS-TRAP`, `MISSING-FAVICON-404`,
  `UX-DESKTOP-CANVAS-SCROLL`), and verified `#checkNativeStructure` / `#lockNativeStructure`
  with `observed_defects: []`. See [`docs/BROWSER_ACCEPTANCE.md`](BROWSER_ACCEPTANCE.md).
- **PR #12 Review Hardening**: Rejected 16-bit/non-RGB PNGs via `IHDR` before Pillow
  truncates (`scripts/reblend-regions.py`, `fidelis/studio/http.py`, `scripts/generate-texture.py`),
  made `fidelis/__init__.py` lazy on `cv2` and scoped `/regions` dispatch (`scripts/web-ui.py`),
  and included `source.shape` in `scripts/generate-texture.py` default `run_id`.
- **Verification**: **185 Python unit tests (`test_*.py`) pass**, plus `tests/smoke-test.sh`,
  `tests/test-web-ui.sh`, `tests/test-release-pipeline.sh`, and `tests/test-browser-acceptance.sh`.
