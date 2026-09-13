# VOSR multi-step fidelity sweep

This experiment exists to answer one question before Fidelis commits to a restoration strategy:

> Can VOSR's 1.4B multi-step model materially improve natural skin and fabric detail over the VOSR 2.0 one-step reference without inventing texture?

It is a **quality-reference experiment**, not the final ARM64 runtime. The final Fidelis engine still targets Android 16 / Termux / aarch64 / Adreno 740.

## Why this branch exists

The previous source-fusion finishing pass reduced useful micro-detail and made the image softer. This experiment deliberately removes that entire stage.

No sharpening, face restoration, source blend, external denoise, synthetic grain, Real-ESRGAN pass, or other finishing step is allowed here. VOSR is judged directly.

## Controlled profiles

All profiles use:

- VOSR 1.4B multi-step checkpoint
- 25 inference steps
- the same seed (`42` by default)
- deterministic VAE posterior mode
- wavelet colour alignment
- the same upscale factor
- the same tiling configuration

Only the two VOSR fidelity controls change:

| Profile | `cfg_scale` | `weak_cond_strength_aelq` | Intent |
| --- | ---: | ---: | --- |
| Natural | 0.50 | 0.10 | Practical VOSR baseline with more reconstruction freedom |
| Fidelity | 1.25 | 0.18 | Balanced source loyalty and fine-detail recovery |
| Strict | 1.75 | 0.23 | Strongest source loyalty in this sweep |

VOSR documents approximately `-0.5` to `2.0` as a useful `cfg_scale` range and trains `weak_cond_strength_aelq` across `0.05` to `0.25`. Higher values of either control tend toward stronger input fidelity.

## Run

From a Linux/CUDA environment containing the official `cswry/VOSR` checkout and the `VOSR_1.4B_ms` checkpoint:

```bash
chmod +x experiments/vosr-fidelity-sweep.sh
VOSR_DIR=/path/to/VOSR \
  experiments/vosr-fidelity-sweep.sh /path/to/source.png ./vosr-fidelity-results
```

For large inputs, enable DiT tiling without changing any other test variable:

```bash
TILE_SIZE=512 VOSR_DIR=/path/to/VOSR \
  experiments/vosr-fidelity-sweep.sh /path/to/source.png ./vosr-fidelity-results
```

The output tree is:

```text
vosr-fidelity-results/
├── natural/
├── fidelity/
├── strict/
└── manifest.json
```

`manifest.json` records the input SHA-256, checkpoint, seed, step count, profile values, output sizes, and output SHA-256 hashes.

## Review protocol

Judge the outputs at native scale first, then inspect 100% and 200% crops. Do not reward an image simply because it looks sharper.

Priority order:

1. **Identity and geometry**: facial proportions, hands, garment construction, logos, seams, hardware and edges must not drift.
2. **Skin**: pores and fine tonal variation may be recovered, but pores must not become repeated dots, grit, freckles, acne, or waxy smoothing.
3. **Fabric**: weave/rib/velour/denim texture must follow folds and construction. Reject repeated synthetic texture or texture that ignores the garment surface.
4. **Hair and fine edges**: individual strands may become clearer, but do not accept invented flyaways or haloed edges.
5. **Tonal realism**: highlights and shadows should remain photographic rather than becoming locally over-contrasted.
6. **Background**: smooth backgrounds should stay smooth. Newly invented wall/floor texture is a failure.

## Decision rule

- If **Fidelity** clearly beats the VOSR 2.0 one-step reference on skin/fabric while preserving geometry, it becomes the new quality target for Fidelis.
- If **Strict** only reduces hallucination by sacrificing useful detail, keep Fidelity as the target.
- If none of the multi-step outputs materially beat the one-step reference, stop spending compute on multi-step VOSR. Keep VOSR 2.0 one-step as the external quality reference and move the engineering effort back to finding or converting an ARM64-native model that reproduces its visual behaviour.

The failed source-fusion branch is not part of this experiment and should not be reintroduced unless new evidence justifies it.
