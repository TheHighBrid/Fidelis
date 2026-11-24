# Structural regions in Studio

Use explicit rectangles to lock logos, seams, zipper teeth and hardware on the
saved precision-base grid. The lock writes into the existing protection mask
and renders a new revision. It preserves existing brush protection and
semantic masks. The latest lock operation records its rectangles and revision.

```bash
.venv/bin/python scripts/structural-roi.py propose --workspace WORKSPACE --job JOB_ID \
  --expected-revision 3 --target texture --max-proposals 8
.venv/bin/python scripts/structural-roi.py inspect --workspace WORKSPACE --job JOB_ID \
  --expected-revision 3 --target texture --roi 130 348 75 65 --roi 241 323 13 122
.venv/bin/python scripts/structural-roi.py lock --workspace WORKSPACE --job JOB_ID \
  --expected-revision 3 --roi 130 348 75 65 --roi 241 323 13 122
.venv/bin/python scripts/structural-roi.py inspect --workspace WORKSPACE --job JOB_ID \
  --expected-revision 4 --roi 130 348 75 65 --roi 241 323 13 122
```

Coordinates are zero-based x, y, width and height on the saved base. Replace
the sample revisions with the current saved revisions. `propose` scans the saved
precision base in bounded stripes for dense strong-edge clusters (`>= 24`
8-bit luminance steps) and optionally scores `changed_pixels` and
`strong_edge_disagreements` against `texture` or `master` (`POST
/api/regions/jobs/<id>/propose-structure`). Proposals are read-only contrast
heuristics (`semantic_proof: false`); they do not prove OCR/logo/hardware
semantics and never auto-lock pixels without explicit operator `lock` review.
Studio can reopen the latest result and display its protection mask. The default
inspection target is the blended master. The `texture` target inspects the
candidate before blending. Reports identify the exact artifact hashes and
revision.

The screen counts changed RGB pixels and horizontal or vertical neighbor
pairs where a strong luminance edge appeared, disappeared or flipped
polarity. The strong-edge threshold is 24 levels on an 8-bit luminance scale.
These counts flag areas for visual review. Zero edge disagreements can occur
even when some pixels changed. Production-corpus validation (`F12`/`F13`)
remains open.

## Photo replay · 2026-11-12

Used the same astronaut image and pinned CPU SegFormer candidate as the prior
audition. The texture pass used inverted RGB as a deliberate stress fixture.

| Region | Changed pixels before lock | Changed pixels after lock | Strong-edge disagreements before → after |
| --- | ---: | ---: | ---: |
| Suit patch | 3,611 / 4,875 | 0 / 4,875 | 887 → 0 |
| Zipper | 156 / 1,586 | 0 / 1,586 | 0 → 0 |
| Fabric panel outside locks | 875 / 875 | 875 / 875 | 1 → 1 |

All pixels outside the two rectangles matched the prior master exactly. All
6,461 locked pixels matched the base. A regression fixture also flags a
one-pixel edge shift between equally sized images across a stripe boundary.
[Photo and model provenance](SEGFORMER_B0_AUDITION.md)

The photo replay passed with ONNX Runtime telemetry disabled. The full Python
suite passed 128 tests with the optional ONNX package absent. Static smoke
tests passed.

## 4x Apple M1 (`2048 × 2048`) NCNN + SegFormer B0 replay · 2026-11-13

Executed on Apple M1 (`Darwin 25.4.0 arm64`, 8 GB unified memory) using a `2048 × 2048` `RealeSR-general-v3` precision base (`bb8ef138dc66be9c...`) and a `2048 × 2048` `ESRGAN-Remacri` texture pass (`f0bcdaaa63828cf4...`) with accepted `SegFormer B0` semantic masks:

| 4x Region (`2048 × 2048` grid) | Rectangle `x, y, w, h` | Changed pixels before lock | Changed pixels after lock | Strong-edge disagreements before → after |
| :--- | :--- | ---: | ---: | ---: |
| Suit patch (4x) | `520, 1392, 300, 260` | `45,771 / 78,000` | `0 / 78,000` | `1,806 → 0` |
| Zipper (4x) | `964, 1292, 52, 488` | `2,367 / 25,376` | `0 / 25,376` | `1 → 0` |

Locking both 4x rectangles (`103,376` total pixels) via `scripts/structural-roi.py lock` completed in `0.591 s` at `158.34 MB` peak RSS, reducing `master_max_abs_diff` to `0` (`locked_pixel_mismatches = 0`) across both regions and preserving bit-exact precision-base pixels in the exported 8-bit (`1d41fbecbc13fc3d...`) and 16-bit (`0ee302f7285d534c...`) batch masters. See [Apple M1 precision-base audition](APPLE_M1_PRECISION_BASE_AUDITION.md#6-end-to-end-42-mp-2048--2048-multi-pass-studio-pipeline-benchmark-on-apple-m1-8-gb).

## Lock a crop in Studio

Open **Inspect native pixels** and click or tap the overview to centre a crop.
Use a 16, 32 or 64 pixel crop for small details, or enter its centre coordinates.
**Propose structural ROIs** queries `POST /api/regions/jobs/<id>/propose-structure`
for contrast-cluster candidates against the selected target, lets you jump the
native crop to each candidate with **Inspect**, and requires an explicit
**Lock ROI** click to commit. **Check crop changes** compares the displayed target
with the precision base. **Lock crop to base** commits the displayed crop at the
saved revision and reopens the same crop against the new master. Save or discard
pending brush and blend edits before applying a lock.
