---
name: multimodal-self-improvement-evaluation
description: Reusable procedure and reference architecture for 3-tier multi-modal evaluation, defect clustering, and profile routing synthesis in AI restoration and generation pipelines.
---

# Multimodal Self-Improvement Evaluation & Routing

This skill provides an end-to-end framework for evaluating image/multimodal restoration pipelines, clustering failures into structural defect classes, and synthesizing specialized profile routing rules.

## 1. 3-Tier Evaluation Architecture

Pipelines must enforce a three-tiered quality gate:

### Tier 1: Deterministic Invariants (Fail-Closed)
- **Dimension Multiplier**: Output resolution must strictly match expected scale factor (e.g. $4\times$).
- **Content Integrity**: No solid black, transparent, or NaN/Inf pixel tiles.
- **Metadata Preservation**: EXIF metadata, ICC profiles, and color space tags must persist across transformation passes.

### Tier 2: Perceptual Quality Metrics
- **PSNR (Peak Signal-to-Noise Ratio)**: Evaluated against reference downscaled ground truths (target $\ge 24.0$ dB).
- **SSIM (Structural Similarity Index)**: Windowed structural similarity check (target $\ge 0.70$).
- **LPIPS Proxy**: High-frequency perceptual distance metric checking edge/texture preservation.

### Tier 3: Psychometric Vision / LLM Judge
- **Dollification / Plastic Skin**: Evaluates over-smoothing on human faces where pores and natural micro-textures are wiped.
- **Ringing Halos**: Detects high-contrast edge over-sharpening artifacts along boundaries.
- **Text Mutation**: Verifies that text glyphs and characters in signage or document scans are not transformed into pseudo-letters or gibberish.

---

## 2. Defect Clustering Taxonomy

When evaluations fail or fall below thresholds, classify errors into root-cause buckets:

| Defect Class | Detection Heuristic | Root Cause |
| :--- | :--- | :--- |
| `MODEL_PLASTIC_SKIN` | Face weight $> 0.70$ + high-frequency loss | Overly aggressive face restoration model / weight |
| `MODEL_RINGING_HALO` | Sharpness proxy $> 0.85$ + contrast halo | Model profile over-sharpening or aggressive tile blend |
| `MODEL_MUTATED_TEXT` | Text density detected + low glyph structural score | Model hallucinates strokes instead of restoring OCR lines |
| `TOOL_BLACK_TILE` | Zero-variance tiles / NaNs in output | VRAM overflow, uninitialized buffer, or CUDA error |
| `PERF_LATENCY_SPIKE` | Processing time / MP exceeds budget | Tile size too small causing excessive overhead |

---

## 3. Profile Routing Synthesizer

When a cluster of defects is identified across a specific input type (e.g. low-light noisy photos, anime, document text):

1. **Extract Domain Features**:
   - `noise_level > 0.05` $\rightarrow$ Low-light noisy
   - `has_faces == True` $\rightarrow$ Portrait
   - `text_density > 0.3` $\rightarrow$ Document / Signage
   - `line_art_score > 0.6` $\rightarrow$ Anime / Illustration

2. **Generate Routing Overrides**:
   - For `MODEL_PLASTIC_SKIN`: Clamp face restoration blend weight $w \le 0.45$.
   - For `MODEL_MUTATED_TEXT`: Route to text-specialized profile (`d2fk-v1` or bicubic fallback) rather than GAN-based models.
   - For `TOOL_BLACK_TILE` / VRAM bottlenecks: Downscale tile size (e.g. 512 $\rightarrow$ 256) and enable cosine-weighted border blending.

3. **Harness Configuration**:
   - Emit candidate routing rules into `routing_rules` map.
   - Run candidate profile against golden regression suites (`golden_cases.jsonl`) to ensure zero Tier 1 regressions before promoting to production.
