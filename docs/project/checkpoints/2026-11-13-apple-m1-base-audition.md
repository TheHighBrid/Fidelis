# Apple M1 precision-base hardware audition checkpoint · 2026-11-13

## Scope and delivery

F05 / MEL-58 target-device precision-base audition on **Apple M1 (`Darwin 25.4.0 arm64`, 8 GB unified memory)** across `RealeSR-general-v3`, `RealSR-DF2K`, and `ESRGAN-Remacri` using checksum-locked `realsr-ncnn` Vulkan engines (`realesrgan-ncnn-vulkan` SHA-256 `c1c35d92...`, `realsr-binary` SHA-256 `4daca3d6...`, `realsr-ncnn` router SHA-256 `a5fbe36b...`).

## Evidence recorded

- Full audition report: [`docs/APPLE_M1_PRECISION_BASE_AUDITION.md`](../../APPLE_M1_PRECISION_BASE_AUDITION.md)
- Four real photographic inputs (`astronaut_nasa_512` `512×512 -> 2048×2048`, `portrait_skin_real` `150×150 -> 600×600`, `fashion_fabric_real` `200×200 -> 800×800`, `product_edges_real` `250×250 -> 1000×1000`) covering portrait/skin, fashion/dark textured fabric, product/hard edges, and multi-ROI logo/hardware/identity protection.
- Measured Apple M1 8 GB performance & memory (`/usr/bin/time -l`):
  - `RealeSR-general-v3`: `515.7–1,804.5 ms`, `0.626–2.324 MP/s` output throughput, `70.94–93.02 MB` peak RSS.
  - `RealSR-DF2K`: `2,019.2–16,390.3 ms`, `0.178–0.256 MP/s` output throughput, `556.84–684.12 MB` peak RSS.
  - `ESRGAN-Remacri`: `2,122.8–16,351.3 ms`, `0.170–0.257 MP/s` output throughput, `408.80–415.06 MB` peak RSS.
- Measured registration & structural ROI screening (`screen_internal_drift` + `fidelis.studio.structure.measure_region`):
  - `0.0 px` registration shift across all 12 runs and all 3 explicit ROIs (`suit_patch`, `zipper`, `face`).
  - `RealSR-DF2K` and `ESRGAN-Remacri` pass all 256 block-coherence checks on `astronaut_nasa_512` (`min_block_coherence = 0.9175` and `0.9724`), whereas `RealeSR-general-v3` flags `WARN` (`min_block_coherence = 0.7900`, `3/256` blocks) on embroidered patch edges.

## Remaining external boundary

- `F05 / MEL-58` now has target-device Apple M1 (8 GB) NCNN Vulkan audition evidence, provenance hashes, peak RSS, and structural ROI screening, while full 60-case real photo corpus execution (`F12-A / MEL-79`) and dual-reviewer human visual signoff (`F13 / MEL-66`) remain required before final commercial default promotion.
