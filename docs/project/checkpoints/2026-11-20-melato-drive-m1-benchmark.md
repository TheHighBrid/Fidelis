# 2026-11-20 — Apple M1 Hybrid Zero-Cost Benchmark (Google Drive Melato Pool)

- **Branch / PR**: `work/unified-studio-20261119` (Draft PR `#82`)
- **Host**: Apple M1 (`Darwin arm64`, 8 GB unified memory)
- **Compute Capabilities (`detect_local_compute_capabilities`)**:
  - `ncnn_vulkan_available`: `true` (`RealeSR-general-v3` via `bin/fidelis upscale` + `realsr-ncnn`)
  - `mps_available`: `false` (`torch` not installed)
  - `onnxruntime_available`: `false` (`onnxruntime` not installed)
  - `cpu_fallback_available`: `true` (`LocalCPUFallbackBackend`, Lanczos-3)
  - `allow_remote_cloud_fallback`: `false`
- **API Spend**: `$0.00` (`cloud_fallback: false`)
- **Dataset**: 25 unique, SHA-256-deduplicated off-repo Melato images from Google Drive `DOUBLE BANG / double bang` (`13QjPgD4QA4jyN7h7bDUV7tzZubSc_HNl`), stored off-repo under `~/melato-corpus/fidelis/drive_benchmark_pool` (`256x256` center ground truth -> `64x64` 4x bicubic input -> `256x256` restoration).

## Measured Results (`measure_scale_matched_metrics`)

| Configuration | Median Latency | Interior Texture Pass | Oversharpen Restraint Pass | Fabric/Hardware Pass | All Detail Gates Pass |
| :--- | ---: | ---: | ---: | ---: | ---: |
| `LocalCPUFallbackBackend` (Lanczos-3) | `1.22 ms` | — | — | — | `2 / 25` |
| `Bicubic` baseline | — | — | — | — | `1 / 25` |
| `RealeSR-general-v3` (`detail_blend_weight=1.00`) | `416.16 ms` | `20 / 25` | `2 / 25` | `25 / 25` | `0 / 25` |
| `RealeSR-general-v3` + Precision Base (`detail_blend_weight=0.60`) | `~416 ms` | `24 / 25` | `6 / 25` | `25 / 25` | `5 / 25` |

## Scope & Evidence Honesty
- This checkpoint records **local Apple M1 (`E2_local_m1_ncnn`) and `E1_cpu_fallback`** measurements only.
- **Open External Gates**:
  - Live ComfyUI SDXL/FLUX ControlNet-Tile GPU worker (`F05-A`, `F06`, `F07`, `gpu_milestone_verified: false`).
  - Curated 60-case `experiments/corpus_manifest.json` held-out acceptance, `Clarity`/`Krea` comparator outputs, and 2-rater blind human study (`F12`, `F13`, `E3`).
  - Physical mobile/tablet QA (`F15`) and owner merge/release signoff (`F16`, `E4`).
