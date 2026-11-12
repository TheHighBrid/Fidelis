# Structural regions in Studio

Use explicit rectangles to lock logos, seams, zipper teeth and hardware on the
saved precision-base grid. The lock writes into the existing protection mask
and renders a new revision. It preserves existing brush protection and
semantic masks. The latest lock operation records its rectangles and revision.

```bash
.venv/bin/python scripts/structural-roi.py inspect --workspace WORKSPACE --job JOB_ID \
  --expected-revision 3 --target texture --roi 130 348 75 65 --roi 241 323 13 122
.venv/bin/python scripts/structural-roi.py lock --workspace WORKSPACE --job JOB_ID \
  --expected-revision 3 --roi 130 348 75 65 --roi 241 323 13 122
.venv/bin/python scripts/structural-roi.py inspect --workspace WORKSPACE --job JOB_ID \
  --expected-revision 4 --roi 130 348 75 65 --roi 241 323 13 122
```

Coordinates are zero-based x, y, width and height on the saved base. Replace
the sample revisions with the current saved revisions. Studio can reopen the
latest result and display its protection mask. The default inspection target
is the blended master. The `texture` target inspects the candidate before
blending. Reports identify the exact artifact hashes and revision.

The screen counts changed RGB pixels and horizontal or vertical neighbor
pairs where a strong luminance edge appeared, disappeared or flipped
polarity. The strong-edge threshold is 24 levels on an 8-bit luminance scale.
These counts flag areas for visual review. Zero edge disagreements can occur
even when some pixels changed. Automatic recognition of construction details
and validation across the production corpus remain open.

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
