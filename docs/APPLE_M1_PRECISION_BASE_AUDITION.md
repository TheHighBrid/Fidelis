# Apple M1 (8 GB) Precision-Base Hardware Audition (`F05` / `MEL-58`)

This document records the target-device precision-base audition executed on **Apple M1 (`Darwin arm64`, 8 GB unified memory)** on `2026-11-13` using the checksum-locked `realsr-ncnn` Vulkan runtime and the three pinned `F05` precision-base candidates (`RealeSR-general-v3`, `RealSR-DF2K`, `ESRGAN-Remacri`).

> **Scope & Evidence Boundary**: This report covers **real Apple M1 (8 GB RAM) NCNN Vulkan inference**, wall-clock latency, `/usr/bin/time -l` peak resident memory (`peak_rss_mb`), downsampled source-consistency metrics (`measure_pipeline_metrics`), and structural ROI / block-drift screening (`screen_internal_drift` + `fidelis.studio.structure.measure_region`) across four real photographic test inputs covering the three required visual classes (portrait/skin, fashion/fabric, product/hard edges, plus multi-ROI portrait/logo/hardware). It does **not** substitute for the external 60-case licensed photographic corpus (`F12-A` / `MEL-79`) or dual-reviewer blind visual signoff (`F13` / `MEL-66`).

---

## 1. Verified Hardware & Runtime Provenance

| Component | Identifier / Path | Pinned Revision | Verified SHA-256 | Size |
| :--- | :--- | :--- | :--- | ---: |
| **Host CPU / SoC** | Apple M1 (`Darwin 25.4.0 arm64`) | 8 GB unified memory | — | — |
| **NCNN Engine (`realesrgan`)** | `~/.local/share/fidelis/runtime/realsr-ncnn/realesrgan-ncnn-vulkan` | `realsr-ncnn-macos-arm64` | `f6fcfbc9aa33c2bd7d1aa4ca0341a018916686522e73b0aaecba14edbf9da06d` | 6,753,904 B |
| **NCNN Engine (`realsr`)** | `~/.local/share/fidelis/runtime/realsr-ncnn/realsr-ncnn-vulkan` | `realsr-ncnn-macos-arm64` | `dc6d6998f3ba578e0a16a9f0fd15a16e92d4f0a870c2294950cbdf977a4d64dc` | 6,751,856 B |
| **`RealeSR-general-v3` (`.param`)** | `models-RealeSR-general-v3/x4.param` | `0fe68041370150c7695816e229dc982bfc06ed58` | `ce766e261369b911c3f3f607266380e6e6133e82699fed5e3b3afa07482c34c1` | 5,976 B |
| **`RealeSR-general-v3` (`.bin`)** | `models-RealeSR-general-v3/x4.bin` | `0fe68041370150c7695816e229dc982bfc06ed58` | `01450f4a79b81c0f1f3eeefc31121167886125c25e41a6d4773e8ec8062528a1` | 2,435,272 B |
| **`RealSR-DF2K` (`.param`)** | `models-DF2K/x4.param` | `a7b0161ee1b8c70843b3facce834cdac63118c41` | `a7f31e75518ad279c179202bf77da9eca3141124a67e5261d97235849e6cc323` | 45,519 B |
| **`RealSR-DF2K` (`.bin`)** | `models-DF2K/x4.bin` | `a7b0161ee1b8c70843b3facce834cdac63118c41` | `a3f5eb53906ef54d5c5d125b2c9dd5f570d9dbb779e3d934df14b5375fd923c1` | 33,424,520 B |
| **`ESRGAN-Remacri` (`.param`)** | `models-ESRGAN-Remacri/x4.param` | `489b523a30aabfb98002b20797ff55fcef6cb1bd` | `859ecba5b3592ecf3e76c93bed65e9f627b5236dd696aae5a84ecf8c93ab65ce` | 42,671 B |
| **`ESRGAN-Remacri` (`.bin`)** | `models-ESRGAN-Remacri/x4.bin` | `489b523a30aabfb98002b20797ff55fcef6cb1bd` | `a43be595c0d743314c30b50fe7ef188be0c61cc55c46ce81adb79ba4b3c3fb7a` | 33,424,520 B |

---

## 2. Photographic Test Inputs

All four test inputs are real photographic crops (not synthetic procedural grids), covering the three required visual classes in `docs/PHOTO_MODEL_CANDIDATES.md`:

| Input ID | Visual Class | Source Dimensions | 4x Output Dimensions | Source SHA-256 |
| :--- | :--- | :---: | :---: | :--- |
| `astronaut_nasa_512` | Full frame: face/identity + NASA logo patch + suit hardware zipper | `512 × 512` | `2048 × 2048` (4.19 MP) | `48d3711f1f40fbbd45b2e3720cf1c084b3b873e02bf292da08a312ca67cf2939` |
| `portrait_skin_real` | Class 1: Portrait / exposed skin, eyes, hairline | `150 × 150` | `600 × 600` (0.36 MP) | `b4a45272f520bbfbb669a118a8a0caa78a6e98a5d5446c1152048d25843bfc84` |
| `fashion_fabric_real` | Class 2: Fashion / textured garment folds, embroidery, patch | `200 × 200` | `800 × 800` (0.64 MP) | `077a8b160032e0a0b7b415219cc38820d8b0268b130055cd5e51a494d6c0fc7e` |
| `product_edges_real` | Class 3: Product / hard metal hardware, collar ring, zipper teeth | `250 × 250` | `1000 × 1000` (1.00 MP) | `7438b31b49304bcd9bc9f460347dd38bfb35e81802a81a6917beb97b54628c38` |

---

## 3. Apple M1 (8 GB) Latency, Peak RSS, and Source-Consistency Results

Every run was executed via `./bin/fidelis upscale --scale 4 --model <candidate>` under `/usr/bin/time -l` to capture kernel maximum resident set size (`peak_rss_mb`). Source-consistency metrics (`PSNR`, `SSIM`, `CIELAB ΔE`, `gradient_coherence_pct`, `gradient_distance_proxy`) compare the 4x output against the input via `fidelis.eval.pipeline_metrics.measure_pipeline_metrics` (`lpips` and `lpips_proxy` remain `null` per `.agents/rules/companion-telemetry-contracts.md`).

| Input ID | Candidate | Elapsed (ms) | Output MP/s | Peak RSS (MB) | PSNR (dB) | SSIM | CIELAB ΔE | Gradient Coherence (%) | Gradient Distance Proxy | 1x Block-Drift Verdict (`max_shift_px` / `min_coherence`) | Output SHA-256 |
| :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :--- | :--- |
| `astronaut_nasa_512` | `RealeSR-general-v3` | **1,804.5** | **2.324** | **93.02** | 33.08 | **0.9724** | 2.32 | 96.31 | 0.0369 | `WARN` (`0.0 px` / `0.7900`, 3/256 blocks) | `0bd66d6a721f4a8a...` |
| `astronaut_nasa_512` | `RealSR-DF2K` | 16,390.3 | 0.256 | 556.84 | **37.09** | 0.9555 | **1.99** | 96.53 | 0.0347 | `PASS` (`0.0 px` / `0.9175`, 0/256 blocks) | `867ff26027084ed2...` |
| `astronaut_nasa_512` | `ESRGAN-Remacri` | 16,351.3 | 0.257 | 411.83 | 37.00 | 0.9503 | 2.03 | **99.22** | **0.0078** | `PASS` (`0.0 px` / `0.9724`, 0/256 blocks) | `a9e2043bfb1c3328...` |
| `portrait_skin_real` | `RealeSR-general-v3` | **574.9** | **0.626** | **70.94** | 33.61 | 0.9749 | 2.51 | 96.11 | 0.0389 | `PASS` (`0.0 px` / `0.8728`, 0/25 blocks) | `83da2f85bf191c7c...` |
| `portrait_skin_real` | `RealSR-DF2K` | 2,019.2 | 0.178 | 684.12 | 34.70 | 0.9595 | 2.58 | 96.59 | 0.0341 | `PASS` (`0.0 px` / `0.9321`, 0/25 blocks) | `1456620021008b8d...` |
| `portrait_skin_real` | `ESRGAN-Remacri` | 2,122.8 | 0.170 | 415.06 | **36.39** | **0.9848** | **2.16** | **99.20** | **0.0080** | `PASS` (`0.0 px` / `0.9743`, 0/25 blocks) | `30e2a6f0e985d26c...` |
| `fashion_fabric_real` | `RealeSR-general-v3` | **515.7** | **1.241** | **73.75** | 30.01 | 0.9720 | 3.79 | 96.18 | 0.0382 | `PASS` (`0.0 px` / `0.8498`, 0/49 blocks) | `5bb4307dffa5c52e...` |
| `fashion_fabric_real` | `RealSR-DF2K` | 3,039.2 | 0.211 | 683.28 | **35.12** | 0.9819 | **2.39** | 96.60 | 0.0340 | `PASS` (`0.0 px` / `0.9133`, 0/49 blocks) | `1d79dcb3920df28c...` |
| `fashion_fabric_real` | `ESRGAN-Remacri` | 3,116.1 | 0.205 | 414.92 | 34.96 | **0.9935** | 2.93 | **99.07** | **0.0093** | `PASS` (`0.0 px` / `0.9735`, 0/49 blocks) | `bf943df6cbd3963e...` |
| `product_edges_real` | `RealeSR-general-v3` | **542.2** | **1.844** | **74.06** | 33.89 | 0.9717 | 2.34 | 95.99 | 0.0401 | `PASS` (`0.0 px` / `0.8035`, 0/64 blocks) | `8e2ad2c2da7c2eb7...` |
| `product_edges_real` | `RealSR-DF2K` | 4,258.2 | 0.235 | 674.91 | **37.41** | 0.9800 | **1.69** | 96.78 | 0.0322 | `PASS` (`0.0 px` / `0.8143`, 0/64 blocks) | `91c18ccda40af6a0...` |
| `product_edges_real` | `ESRGAN-Remacri` | 4,367.6 | 0.229 | 408.80 | 36.60 | **0.9881** | 2.26 | **98.93** | **0.0107** | `PASS` (`0.0 px` / `0.9647`, 0/64 blocks) | `efd2b56b528a3704...` |

---

## 4. Structural ROI & Edge-Disagreement Screening (`astronaut_nasa_512`)

Using both `fidelis.postprocess.roi_protection.screen_internal_drift` (`MEL-64`) and `fidelis.studio.structure.measure_region` (`threshold = 256`) on the three explicit ROIs of `astronaut_nasa_512` (`suit_patch` `[130, 348, 75, 65]`, `zipper` `[241, 323, 13, 122]`, `face` `[183, 94, 75, 65]`):

| Candidate | ROI ID | Kind | Registration Shift (`px`) | Edge Coherence | Mean Abs Diff | Max Abs Diff | Strong-Edge Disagreements (`threshold=256`) |
| :--- | :--- | :--- | ---: | ---: | ---: | ---: | ---: |
| `RealeSR-general-v3` | `suit_patch` | `logo` | `0.0` | `0.9032` | `11.519` | `74` | `971 / 4875` |
| `RealeSR-general-v3` | `zipper` | `hardware` | `0.0` | `0.9376` | `6.090` | `62` | `102 / 1586` |
| `RealeSR-general-v3` | `face` | `identity` | `0.0` | `0.9766` | `3.509` | `66` | `211 / 4875` |
| `RealSR-DF2K` | `suit_patch` | `logo` | `0.0` | `0.9523` | `5.649` | `57` | `912 / 4875` |
| `RealSR-DF2K` | `zipper` | `hardware` | `0.0` | `0.9402` | `4.077` | `30` | `92 / 1586` |
| `RealSR-DF2K` | `face` | `identity` | `0.0` | `0.9856` | `3.263` | `20` | `165 / 4875` |
| `ESRGAN-Remacri` | `suit_patch` | `logo` | `0.0` | `0.9816` | `5.127` | `38` | `624 / 4875` |
| `ESRGAN-Remacri` | `zipper` | `hardware` | `0.0` | `0.9849` | `3.446` | `40` | `50 / 1586` |
| `ESRGAN-Remacri` | `face` | `identity` | `0.0` | `0.9964` | `2.734` | `36` | `114 / 4875` |

---

## 5. Architectural Findings for `F05 / MEL-58`

1. **Zero Geometric Registration Shift Across All Three Candidates**:
   - All three NCNN precision-base candidates maintain `0.0 px` phase-correlation shift across every evaluated block and explicit ROI on Apple M1 Vulkan (`realsr-ncnn`).
2. **Memory Headroom on 8 GB Unified-Memory Apple Silicon**:
   - Even the 33.4 MB RRDB models (`RealSR-DF2K` at `556.8–684.1 MB` peak RSS, `ESRGAN-Remacri` at `408.8–415.1 MB` peak RSS) execute comfortably within the 8 GB unified-memory budget on 4.2 MP (`2048 × 2048`) outputs without tiling artifacts or swap pressure.
   - `RealeSR-general-v3` (`2.4 MB` weights) stays under `94 MB` peak RSS and completes `512 × 512 -> 2048 × 2048` in `1.80 s` (`9.1x` faster than `RealSR-DF2K`).
3. **Why Dual-Mode Routing (`RealSR-DF2K` vs. `RealeSR-general-v3`) & Structural ROI Protection Are Required**:
   - `RealeSR-general-v3` exhibits higher edge-coherence loss on fine woven/embroidered patches and dark fabric (`min_block_coherence = 0.7900` `WARN` on `astronaut_nasa_512`, `PSNR = 30.01 dB` / `ΔE = 3.79` on `fashion_fabric_real`). It is therefore best suited as the **fast interactive preview / mobile-general lane** (`BSD-3-Clause`), whereas `RealSR-DF2K` (`PSNR = 35.12–37.41 dB`, `ΔE = 1.69–2.58`, `0` blocks flagged) and `ESRGAN-Remacri` (`gradient_coherence = 98.93%–99.22%`, lowest ROI edge disagreements) provide superior structural fidelity for photographic masters, subject to commercial license clearance recorded in `config/model-provenance-v1.json`.
   - Even on `RealSR-DF2K` and `ESRGAN-Remacri`, unmasked SR modifies `99.7%+` of logo/text pixels (`4860–4873 / 4875` pixels changed on `suit_patch`), confirming the necessity of Studio's explicit structural ROI locks (`fidelis/studio/structure.py` + `fidelis/postprocess/roi_protection.py`) so protected text, logos, and hardware remain bit-exact to the precision base when generative texture layers are blended.
