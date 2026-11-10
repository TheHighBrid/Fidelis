# Region reblend: initial working component

This CLI composites existing precision and generated passes. It does not generate
texture, run segmentation, resize images, or recover hidden details. It is the
foundation for the Studio's future editable regional workflow.

Inputs: identically sized and spatially registered **8-bit RGB PNGs in untagged
sRGB**, normalized to EXIF orientation 1. Convert other colour spaces explicitly
before use. ICC-tagged, alpha, and 16-bit passes are intentionally rejected by this
first CLI. Equal dimensions alone do not prove registration; supply a correctly
aligned candidate. It never silently resizes either pass.

Create an NPZ containing float masks of shape `(height, width)` with values in
`[0,1]`. Supported keys: `skin`, `hair`, `fabric`, `protected`, `confidence`,
`edge_guard`. `confidence` is required by the CLI. Missing semantic masks are zero.
Unknown regions stay unchanged. A fully protected pixel is copied exactly from
the precision base. Fractional protection attenuates the generated contribution.
Mask confidence is a routing input, not a calibrated probability of correctness.

Run using the project interpreter:

```bash
.venv/bin/python scripts/reblend-regions.py base.png texture.png master.png \
  --masks regions.npz --profile luxury_apparel \
  --skin 0.25 --hair 0.20 --fabric 0.15
```

This writes `master.png` and `master.png.recipe.json` with input/output hashes,
resolved blend weights, dimensions, and an unsigned execution record. It does
not claim C2PA signing. Both writes use atomic file replacement individually;
the image/sidecar pair is not a transactional database commit. Output files may
replace previous exports; source paths cannot be overwritten.

The default blend candidates are intentionally conservative and **not visually
certified presets**. `packshot_strict` rejects nonzero generation overrides.
Re-run the command with new blend weights to reuse the same generated candidate
without another inference call. Composition uses linear-light sRGB, not arithmetic
averaging of gamma-encoded bytes. No grain, sharpening or global colour finishing
is added after pixel protection.

This implementation is full-frame and intended for correctness testing first.
It does not yet implement the planned byte-budgeted streaming reblend, interactive
brush UI, model adapter or colour-managed high-precision export path.

Tests:

```bash
.venv/bin/python -m unittest discover -s tests -p 'test_regions.py' -v
```
