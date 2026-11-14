# Structural ROI protection and internal drift screening (`F10` / `MEL-64`)

F10 guards geometry-sensitive structures (`logo`, `text`, `seam`, `hardware`,
`identity`, `alpha_boundary`, `background`) across already-aligned sRGB passes and
screens for localized spatial drift hidden beneath matching image dimensions.

## Contracts and invariants

- **Explicit overrides always win.** Default or corpus `policy: "preserve"` locks ROI
  pixels into `protected` (`1.0`). Setting `override: "unlock"` opens an automatically
  protected ROI box; setting `override: "lock"` forces a `protected` lock even when
  `policy` is `"texture_allowed"`. Pre-existing user `protected` canvas locks are never
  weakened.
- **Sobel is a secondary heuristic, never semantic proof.** Enabling
  `use_sobel_heuristic=True` populates `edge_guard` cleanly capped below `1.0` and
  cleared inside `override: "unlock"` boxes. Sobel gradient fires on skin pores and
  fabric weave and can miss low-contrast hardware; it does not verify semantic identity.
- **Equal dimensions do not imply internal registration.** [`screen_internal_drift`](fidelis/postprocess/roi_protection.py)
  rejects size mismatches without resizing and searches block-grid and per-ROI patch
  displacements plus local gradient coherence. On composed `master` outputs, every
  expected-locked pixel must match `base` bit-for-bit (`LOCKED_EXACT` vs `LOCK_VIOLATION`).

## Usage

```bash
.venv/bin/python scripts/screen-roi-drift.py \
  --base base.png \
  --candidate candidate.png \
  --master master.png \
  --rois-json rois.json \
  --out-masks-npz roi_masks.npz \
  --fail-on-drift
```

## Current boundaries

Fixture tests verify local shift detection (`>= 1.5 px` warn / `>= 2.5 px` fail),
exact-lock pixel verification on composed outputs, override precedence, flat
backdrop stability, and CLI exit contracts. Live model candidate outputs, OCR text
verification, and cleared 60-case corpus ROI acceptance (`F12`/`F13`) remain open.
# Opt-in product upscale

```bash
bin/fidelis product-upscale input.png output.png --model RealeSR-general-v3
```

Use a normalized 8-bit sRGB RGB PNG. Output is 4× with a cap of 8 million
output pixels. The command preserves source-derived edge neighborhoods
exactly against a bicubic baseline and feathers into the model output
in linear light. For critical logos, seams and hardware, pass
`--rois-json FILE` with a JSON list of ROI records using the existing
`id`, `kind`, `policy`, `rect` and optional `override` fields. Rectangles
are `[x,y,width,height]` in **input** pixels. Automatic edge locking does
not recognize semantic features. Existing upscale and Studio defaults
are unchanged.

For fine texture, the product command checks whether the model retains
source-aligned luminance detail relative to the bicubic baseline. Where
the model removes that detail, it blends back toward the baseline.
This check does not establish perceptual quality and does not recover
detail absent from the source.
