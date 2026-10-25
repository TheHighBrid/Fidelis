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
- **CI & Test Suite**:
  - Expanded GitHub Actions workflow to a multi-OS matrix (`ubuntu-latest` and `macos-latest`).
  - Added regression test suites for metrics evaluation and audition report generation (7/7 tests passing).

## [2.1.0] - 2026-09-28
- Removed source-fusion finishing pass after empirical testing showed loss of micro-detail.
- Added VOSR 1.4B multi-step sweep experiment with fail-closed manifests.
- Implemented atomic model registry with SHA-256 provenance in native Termux CLI.
- Curated initial candidate catalog in `config/photo-candidates.tsv`.
