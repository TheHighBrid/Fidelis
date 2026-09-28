# Fidelis photo-model candidate lane

This document records the first ARM64-compatible photo candidates selected after the Nomos8kSC baseline failed Fidelis visual expectations on skin and fabric.

The goal is not to crown a model from reputation or sharpness. Every candidate must be run through the same Fidelis source set and judged against the project's quality acceptance gate.

## Source verification

The candidate files below were fetched from immutable revisions of `tumuyan2/realsr-models` and verified in GitHub Actions on 2026-09-28 before their hashes were added to `config/photo-candidates.tsv`.

| Fidelis name | Role | Pinned revision | Param SHA-256 | Bin SHA-256 | Weight size |
| --- | --- | --- | --- | --- | ---: |
| `RealeSR-general-v3` | mobile-general | `0fe68041370150c7695816e229dc982bfc06ed58` | `ce766e261369b911c3f3f607266380e6e6133e82699fed5e3b3afa07482c34c1` | `01450f4a79b81c0f1f3eeefc31121167886125c25e41a6d4773e8ec8062528a1` | 2,435,272 B |
| `RealSR-DF2K` | photo-fidelity | `a7b0161ee1b8c70843b3facce834cdac63118c41` | `a7f31e75518ad279c179202bf77da9eca3141124a67e5261d97235849e6cc323` | `a3f5eb53906ef54d5c5d125b2c9dd5f570d9dbb779e3d934df14b5375fd923c1` | 33,424,520 B |
| `ESRGAN-Remacri` | balanced-general | `489b523a30aabfb98002b20797ff55fcef6cb1bd` | `859ecba5b3592ecf3e76c93bed65e9f627b5236dd696aae5a84ecf8c93ab65ce` | `a43be595c0d743314c30b50fe7ef188be0c61cc55c46ce81adb79ba4b3c3fb7a` | 33,424,520 B |

The installer rejects either file when its SHA-256 differs from the catalog. A checksum failure occurs before `fidelis model-add`, so an already installed model is not replaced by unverified bytes.

## Why these three

### 1. RealeSR-general-v3

**First priority.** This is the small general-image Real-ESRGAN v3 candidate. It is dramatically lighter than the RRDB candidates and is therefore the strongest first test for the actual Android/ARM64 product goal. The upstream Real-ESRGAN checkpoint is BSD-3-Clause. The small size is useful only if skin, fabric and geometry survive the Fidelis gate.

### 2. RealSR-DF2K

**Photo-fidelity comparator.** This comes from the RealSR family prepared for the same RealSR-NCNN runtime. It is much heavier, but it gives the mobile candidate a serious photographic reference inside the local NCNN lane. Model/distribution terms must be reviewed before any commercial bundling.

### 3. ESRGAN-Remacri

**Balanced community comparator.** Remacri is included because it is a general-purpose ESRGAN candidate already prepared for RealSR-NCNN. It is evaluation-only until its model license is verified clearly enough for commercial distribution.

## Installation

List the curated candidates:

```bash
bash scripts/install-photo-candidate.sh list
```

Install one candidate:

```bash
bash scripts/install-photo-candidate.sh RealeSR-general-v3
```

Install the heavier comparators when needed:

```bash
bash scripts/install-photo-candidate.sh RealSR-DF2K
bash scripts/install-photo-candidate.sh ESRGAN-Remacri
```

The installer downloads from the pinned revision, verifies both files, delegates installation to `fidelis model-add`, then records source revision, candidate role and the license note in `fidelis-model.json`.

## Device benchmark

The normal device gate is one command. With no model list, Fidelis automatically benchmarks the first mobile candidate against the installed Nomos baseline:

```bash
bash scripts/benchmark-photo-candidates.sh source.jpg ./benchmark
```

If `RealeSR-general-v3` is not installed yet, the benchmark installs it through the checksum-locked candidate installer first. The baseline is never downloaded implicitly.

To benchmark the larger local shortlist explicitly:

```bash
bash scripts/benchmark-photo-candidates.sh source.jpg ./benchmark \
  RealeSR-general-v3 \
  RealSR-DF2K \
  ESRGAN-Remacri \
  ESRGAN-Nomos8kSC
```

The benchmark writes **one standalone PNG per model**. It does not create a collage, contact sheet, or combined image.

A successful run also writes `benchmark.json` with:

- exact source path, byte count and SHA-256
- engine SHA-256, scale and tile size
- host architecture and kernel
- complete model provenance from `fidelis model-info`
- per-model elapsed inference time in milliseconds
- per-output filename, byte count and SHA-256
- total benchmark elapsed time

The benchmark fails closed. Starting a new run invalidates the previous `benchmark.json`; a replacement is written only when all selected models produce non-empty outputs. An engine that exits successfully without creating an image therefore cannot leave stale success evidence behind.

## Visual audition protocol

Do not evaluate one convenient image. Use at least these source classes:

1. **Portrait / exposed skin**: pores, tonal transitions, hairline, eyes, hands if present.
2. **Fashion / dark textured fabric**: black fabric, knit, denim, velour, leather, seams, embroidery and logos.
3. **Product / hard edges**: metal hardware, zippers, eyewear, typography, smooth backgrounds and specular highlights.

Run the same model set on each source. If the upstream APK also includes `Real-ESRGAN`, include it as an additional official baseline.

For ad hoc comparisons where runtime evidence is unnecessary, `fidelis audition` remains available and produces standalone outputs plus its own provenance manifest.

## Decision order

Judge candidates in this order:

1. identity and geometry preservation
2. natural skin texture
3. fabric texture that follows real folds rather than repeated enhancement patterns
4. clean hair, seam and hardware edges without halos
5. natural tonal roll-off
6. smooth backgrounds staying smooth
7. runtime cost on the reference Android device

A sharper image loses if it invents pores, weave, edges or geometry.

### Promotion rule

- Promote `RealeSR-general-v3` if it meets the visual gate closely enough while retaining its large runtime-size advantage.
- If it is too soft or misses useful real detail, compare `RealSR-DF2K` as the local fidelity ceiling.
- Keep Remacri only if it produces a meaningful visual improvement and its licensing is resolved.
- Nomos8kSC remains a reproducible negative/baseline reference, not the target to optimize around.
