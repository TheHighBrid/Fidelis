# Colour-managed, straight-alpha and 8/16-bit export (`F11` / `MEL-65`)

This contract extends Fidelis beyond untagged 8-bit sRGB PNG exports
([`reblend-regions.py`](../scripts/reblend-regions.py)) into explicit EXIF orientation
normalization, LittleCMS / float64 Matrix-TRC colour management, straight-alpha
preservation, and lossless 8-bit / 16-bit PNG and TIFF exports.

## Modules and CLI

- Module: [`fidelis/postprocess/managed_export.py`](../fidelis/postprocess/managed_export.py)
- CLI: [`scripts/export-master.py`](../scripts/export-master.py)
- Regression tests: [`tests/test_managed_export.py`](../tests/test_managed_export.py)

## Key invariants

1. **Deliberate orientation normalization, no implicit resizing.** EXIF
   orientations `1..8` are normalized before composition so grids align cleanly
   with `ImageOps.exif_transpose` semantics, and exported PNG/TIFF masters emit
   explicit upright orientation `1`. Normalized dimension mismatches still fail
   closed without resizing.
2. **Straight alpha preservation.** `RGBA` base passes keep straight (unassociated)
   alpha unchanged (`alpha_mode="preserve_base"`), gate generated blend weight by
   base alpha, keep RGB on fully transparent pixels untouched, and encode TIFF
   `ExtraSamples=2` (`unassociated`) cleanly. Associated/premultiplied alpha TIFFs
   and unexpected alpha mismatches (`RGB` base vs `RGBA` texture) fail closed.
3. **Real working/export precision without detail masquerading.** Linear-light
   blending executes in `float64` across `uint8` or `uint16` passes. When an
   8-bit input is explicitly exported into a 16-bit container (`--bit-depth 16`),
   the sidecar records `container_precision_exceeds_source: true` and
   `newly_recovered_source_detail: false` so containers never claim recovered bit
   depth.
4. **Honest ICC management.** Tagged RGB ICC profiles are validated (`acsp` /
   `RGB `). Cross-profile transforms run in `float64` Matrix-TRC when supported
   or LittleCMS `ImageCms` for 8-bit / LUT intents; 16-bit LUT truncation fails
   closed unless `--allow-8bit-lut` is explicitly provided.
5. **Default grain remains off; hard locks always win last.** `grain_strength`
   defaults to `0.0` (`grain_enabled: false`). Even when opt-in grain is set,
   `protected == 1.0`, `alpha == 0.0`, and zero-alpha base pixels are restored
   bit-for-bit after quantization.

## Usage

```bash
.venv/bin/python scripts/export-master.py base.tif texture.png master.png \
  --masks regions.npz --profile luxury_apparel --bit-depth auto --icc-policy preserve
```

## Boundaries (not complete `F11` signoff)

This standalone module and CLI are verified on controlled 8-bit/16-bit PNG/TIFF
and synthetic ICC fixtures; integrating non-sRGB/16-bit ingest directly into
[`fidelis/studio/http.py`](../fidelis/studio/http.py) /
[`fidelis/studio/store.py`](../fidelis/studio/store.py) and running over live
`F06` outputs / `F10` ROI cases remain open.
