---
trigger: always_on
description: Standardize companion agent telemetry emission, non-blocking delivery, and unauthenticated ingestion.
---

# Companion Telemetry Contracts

When instrumenting companion agents (Fidelis, Allo, Pedit) that communicate with the Autonomous Improvement Kernel:

## Mandatory Rules:
1. **Non-Blocking Telemetry Ingestion**:
   - Spans and telemetry payloads dispatched to `/api/telemetry/trace?project={name}` must never halt the primary processing pipeline if the telemetry receiver is offline or returns an error.
   - Use strict connection timeouts ($\le 2.0$ seconds) and catch all transport errors (`urllib.error.URLError`, `ConnectionRefusedError`, `socket.timeout`).
2. **Local Companion Bypass**:
   - Kernel routers must allow service-to-service span ingestion from local agents without requiring user-facing `X-API-Key` authentication headers.
3. **Structured Span Attributes**:
   - Multi-modal pipeline traces must include:
     - `input_dimensions`: `[width, height]`
     - `noise_level`: float
     - `model_profile`: string identifier
     - `tile_size`: integer
     - `vram_peak_mb`: float
     - `processing_time_per_megapixel`: float
     - `c2pa_status`: string (`signed`, `unsigned`, `manifest_generated`)
     - `psnr`, `ssim`: measured floats, or JSON `null` when unavailable
     - `lpips` / `lpips_proxy`: JSON `null` unless the named implementation is actually computed
     - `gradient_distance_proxy`: measured gradient-coherence complement under its own name
     - `metric_context`: schema version, reference/comparison method, availability and reason when missing
   - Never fill missing measurements with plausible constants. A gradient-derived
     value must not be labelled LPIPS. Source-consistency measurements must be
     distinguished from paired ground-truth accuracy. Numeric `*_ms` timing values
     keep their unit; any compatibility alias must name the same unit explicitly.
