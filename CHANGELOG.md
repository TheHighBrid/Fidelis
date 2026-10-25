# Fidelis Changelog

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
