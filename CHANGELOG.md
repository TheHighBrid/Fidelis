# Fidelis Changelog

## Unreleased live-worker and workflow schema preflight · 2026-11-11

- Added `config/worker-preflight-policy-v1.json`, `fidelis/studio/worker_preflight.py`, and `scripts/worker-preflight.py` (`F05-A` / `MEL-76`).
- Enforced explicit owner/access metadata, loopback/SSH-tunnel endpoint constraints, zero paid remote spend, and secret-pattern rejection before emitting receipts.
- Added exported ComfyUI workflow inspection against live `/object_info` (missing node classes, required inputs, and installed checkpoint/VAE/LoRA choices).
- Recorded 132 passing Python tests, HTTP/static smoke, and editor syntax checks.
- See [worker preflight receipt](docs/project/checkpoints/2026-11-11-worker-preflight.md).


## Unreleased mask suggestion interface · 2026-11-10

- Added source-bound class probability import, explicit label routing and conservative confidence/boundary gates.
- Added persisted staging/preview/accept/discard; active master stays unchanged until acceptance.
- Fill-only-unclassified merge preserves manual masks, erasures, edge guards and protection.
- Recorded 125 passing Python tests, HTTP/static smoke and editor syntax checks.
- F09 remains partial: no configured/qualified automatic segmentation model or live accuracy result.
- See [suggestion receipt](docs/project/checkpoints/2026-11-10-mask-suggestions.md).


## Unreleased corpus tooling checkpoint · 2026-11-10

- Added versioned 60-slot protocol/split design and explicit rights/hash/group/ROI inventory.
- Added safe audit, unsigned freeze and re-verification commands with leakage and duplicate checks.
- Audited eight legacy regression assets; no production case or permission was inferred.
- Recorded 114 passing Python tests and static smoke/compilation checks.
- F12-A remains partial: 60 production slots and reviewed permissions/coverage are still missing.
- See [corpus receipt](docs/project/checkpoints/2026-11-10-corpus-inventory.md).


## Unreleased native inspection checkpoint · 2026-11-10

- Added revision-pinned, unresampled RGB crop responses and a read-only paired inspector.
- Added 100/200% CSS-pixel scales, coordinate/overview selection and bounded crop sizes.
- Preserved unsaved edits; reject stale/mismatched pairs and invalidate old asynchronous loads.
- Recorded 102 passing Python tests, HTTP/static smoke and JavaScript syntax checks.
- In Review in PR #12. Actual browser/device rendering and live quality remain open.
- See [native inspection receipt](docs/project/checkpoints/2026-11-10-native-inspection.md).


## Unreleased background generation checkpoint · 2026-11-10

- Added an opt-in durable local generation queue with scoped status/cancel/resume API and editor controls.
- Preserved run identity across timeouts/restarts and revision-safe candidate application.
- Local cancellation blocks late application without global ComfyUI interruption; remote work may continue.
- Recorded 92 passing Python tests, web HTTP/static smoke and editor syntax checks.
- In Review in PR #12; live/device acceptance and generated-cache quota/retention remain open.
- See [async receipt](docs/project/checkpoints/2026-11-10-async-generation.md).


## Unreleased pipeline integrity checkpoint · 2026-11-10

- Corrected unsigned provenance status, large-input tiler execution and explicit runtime selection.
- Defaulted local HTTP/Compose publication to loopback and removed public firewall/deployment promotion.
- Replaced invented metric defaults/pseudo-LPIPS with nullable measurements and explicit reference context.
- Corrected RGB handling and physical CIE76 colour differences; added optional paired ground-truth CLI input.
- Recorded 77 passing Python tests plus shell checks. See [receipt](docs/project/checkpoints/2026-11-10-pipeline-integrity.md).
- Pending PR #12 review/merge; no live inference or production release certification.

## Unreleased Studio engineering checkpoint · 2026-11-10

Implementation remains in open PR #12 on `feat/region-aware-studio` at `5f32fba`.
This section is not a production release announcement.

- Added protected region composition, persistent artifacts/revisions and storage budgets.
- Added manual masks, paint/erase, unsaved undo/redo and regional review/export.
- Added a protocol-tested local ComfyUI adapter, run identity/reconciliation and runtime doctor.
- Recorded 62 local Python tests plus web UI integration/smoke/JS checks at that SHA.
- Published contributor documentation, a formal handoff and the Linear Fidelis project.
- Live GPU quality, device acceptance, automatic masks, managed precision exports,
  held-out competitive benchmarks and release gates remain open.

The historical sections below are retained from earlier repository notes. Their
quality, timing, model-promotion and zero-drift language is not renewed certification.
Use `docs/project/STATUS.md` and actual evidence for current claims.

## [3.1.0] - 2026-10-25

### Added
- **100% Local Portrait & Skin Pore Restoration Engine**:
  - Added `scripts/restore-portrait.py` and `fidelis portrait INPUT OUTPUT [-w FIDELITY]` CLI command.
  - Powered by discrete Vector-Quantized codebook priors (`CodeFormer ONNX`) and neural face detection (`YuNet`).
  - Restores authentic dermal micropores, eyelash separation, and iris clarity without plastic "dollification" in ~3.7 seconds on Apple Silicon.
  - Adjustable Fidelity Slider ($w \in [0.30, 0.95]$): balances authentic micro-pore synthesis ($w=0.45$) with zero geometric/identity drift ($w=0.70$, **Fidelis Rule #1**).
  - Multi-stage pipeline: optional 4x NCNN super-resolution + discrete codebook skin texture refinement.
- **Studio Web UI Dual-Model Comparator & Portrait Engine**:
  - Added dual-model comparison selector (`Source vs Model` or `Model vs Model`) with differential metrics HUD.
  - Integrated Portrait Pore Engine checkbox and live interactive fidelity slider ($w$) into Studio Web UI (`fidelis ui`).
  - Added pre-staged evaluation portrait sample buttons for instant testing.
- **Visual Hallucination & Drift Heatmap Generator**:
  - Added `fidelis heatmap SOURCE [UPSCALED] [-o OUT_PNG]` and `scripts/generate-delta-heatmap.py`.
  - Generates thermal false-color maps of high-frequency Sobel gradient changes and luminance drift.
- **Apple Silicon Hardware Profiler**:
  - Added `fidelis benchmark-macos` and `scripts/macos-benchmark.sh` profiling SoC topology, unified memory, wall-clock latency, and true kernel peak RSS RAM via `/usr/bin/time -l`.
- **4x-UltraSharp Photographic Model**:
  - Registered and integrated `4x-UltraSharp` (FP16 NCNN, 33.4 MB) with SHA-256 provenance verification.
- **OVHcloud Production Container & Deployment Suite**:
  - Added production `Dockerfile` (Python 3.12, OpenCV, NCNN, ONNX Runtime) and `docker-compose.yml`.
  - Added `deploy/ovh-deploy.sh` supporting automated local or remote SSH deployment with UFW firewall configuration.
- **Android App & Automated APK Build Pipeline**:
  - Added native Android client under `android/` with full-screen WebView, Material Design, and camera/gallery file picker bridge.
  - Added `.github/workflows/android-apk.yml` compiling and publishing `fidelis-android.apk` directly to GitHub Releases.
- **Artifact Resolution**:
  - Resolved DF2K 256px tile grid-line slicing by standardizing on `tile=0` overlap in runtime dispatchers.

## [3.0.0] - 2026-10-24

### Added
- **Multi-OS Runtime Parity**:
  - Native macOS Apple Silicon GPU (Metal/Vulkan via MoltenVK) runtime installer (`scripts/install-macos-runtime.sh`).
  - Intelligent engine dispatch wrapper supporting both Compact SRVGGNet models and RRDBNet models.
  - Cross-platform path resolution compatible with macOS BSD and Linux/Termux GNU coreutils.
- **Model Promotion & Benchmarking**:
  - Full multi-class evaluation across real-world photographic test crops (Portrait Skin, Fashion Fabric, and Product Edges).
  - Formal promotion of `RealeSR-general-v3` (2.4 MB) as the primary mobile model target, achieving highest SSIM (0.88 - 0.93) and ~3.7× lower background noise synthesis than DF2K.
  - Curated evaluation crops under `experiments/eval_crops/`.
- **Seamless Tiled Upscaling**:
  - Added `scripts/tiled-upscale.py` and `fidelis upscale --tiled` with 2D cosine overlap blending for gigapixel fashion photography.
- **Master Evaluation Dashboard**:
  - Added `scripts/generate-master-dashboard.py` generating aggregate executive scorecards and tabbed crop comparisons in a single self-contained HTML file.
- **Photographic Fidelity Metrics**:
  - Added `scripts/evaluate-fidelity-metrics.py` computing PSNR, SSIM, mean chromatic drift, edge gradient energy, and background flatness restraint.
- **First-Class CLI Subcommands**:
  - Added `fidelis evaluate`, `fidelis report`, and `fidelis eval-crops`.
- **Model Conversion Pipeline**:
  - Added `scripts/convert-to-ncnn.py` supporting PyTorch/ONNX to NCNN FP16 conversion with automatic SHA-256 registry integration.
- **Studio Web UI**:
  - Added zero-dependency browser interface (`fidelis ui`) running on `http://127.0.0.1:8765`.
  - Real-time before/after split slider, 100% and 200% native pixel zoom, drag-and-drop file loading.
  - Live Quality Inspection HUD displaying PSNR, SSIM, color drift, edge shift, gradient coherence, and Fidelis Rule #1 status badge.
- **Batch Audition & Lookbook Generation**:
  - Added `fidelis batch-audition` and `scripts/batch-audition.sh` to audit multi-shot photo shoots across candidate models.
  - Generates unified, interactive `lookbook.html` portfolios with cross-crop scorecards.
- **Geometric & Identity Drift Detector**:
  - Added `fidelis detect-drift` and `scripts/detect-drift.py` enforcing Fidelis Quality Rule #1 mathematically.
  - Quantifies edge shift displacement via distance transform, Sobel gradient coherence, and hallucination percentage from flat regions.
  - Includes `--strict` fail-closed mode for automated gate evaluation.
- **VOSR 2.0 One-Step Baseline Comparator**:
  - Added `--include-onestep` and `INCLUDE_ONESTEP=1` to `experiments/vosr-fidelity-sweep.sh` to run the 1-step distillation baseline alongside multi-step profiles.
  - Updated Google Colab notebook with an interactive checkbox toggle.
- **Air-Gapped / Offline Deployment Packager**:
  - Added `scripts/package-offline-bundle.sh` creating self-contained offline deployment archives with bundled model weights, evaluation crops, and `install-offline.sh`.
- **Automated GitHub Release Workflow**:
  - Added `.github/workflows/release.yml` automating release packaging and asset uploads on tag creation.
- **CI & Test Suite**:
  - Expanded GitHub Actions workflow to a multi-OS matrix (`ubuntu-latest` and `macos-latest`).
  - Added full regression test coverage across 10 test runners (10/10 passing).

## [2.1.0] - 2026-09-28
- Removed source-fusion finishing pass after empirical testing showed loss of micro-detail.
- Added VOSR 1.4B multi-step sweep experiment with fail-closed manifests.
- Implemented atomic model registry with SHA-256 provenance in native Termux CLI.
- Curated initial candidate catalog in `config/photo-candidates.tsv`.
