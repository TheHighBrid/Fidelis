# Native image-pixel inspection

Open a saved job in `/regions` and choose **Inspect native pixels**. This separate,
read-only view fetches genuine pixels from the saved base and final blend, or the
raw candidate. It does not enlarge the reduced overview or alter masks/unsaved edits.

## Use the inspector

- Choose a centre using integer X/Y coordinates, or click/tap the overview while
  **Inspect / pan** is selected. Overview selection is a position locator; the
  displayed original-pixel coordinates and crop range identify the exact saved data.
- Select a 128, 256 or 512 pixel crop. At image edges the window shifts inward;
  for smaller images its width/height shrink to the actual image. It never pads,
  wraps, stretches or resamples the stored pixels.
- Compare base/final or base/raw candidate using the divider. Both sides use the
  same rectangle and saved revision. The caption records the inclusive pixel range.
- **100%** means one image pixel per CSS pixel. **200%** means two CSS pixels per
  image pixel, using pixelated rendering. Browser zoom, display scaling and device
  pixel ratio affect physical screen pixels; this is not a physical-display promise.
- Scroll the crop on narrow/mobile layouts. Its CSS dimensions do not shrink to fit.
  The existing overview zoom remains explicitly labelled in preview pixels.

The panel shows the saved revision, including when there are unsaved mask/slider
changes. Save and reopen inspection to review those changes. Selecting another
job, saving/reloading a revision or deleting a job invalidates pending pairs.

## Pair consistency and failures

Both images finish decoding before either is inserted into the comparison. Older
loads cannot replace a newer request, and a failed/mismatched pair stays hidden.
A stale revision returns 409 rather than quietly serving newer pixels on one side.
Reload the job after a background result or edit changes its saved revision.
Equal grid coordinates do not prove that a generated object remained geometrically
faithful; visual/ROI drift evaluation remains separate.

## Local API and resource boundary

```text
GET /api/regions/jobs/{id}/crop?role=base&revision=3&x=100&y=200&width=256&height=256
```

Supply exactly one each of `role`, `revision`, `x`, `y`, `width`, `height`. Role is
`base`, `texture` or `master`; revision must be positive. Coordinates are zero-based
nonnegative integers. Sides are 1..512 pixels and the complete rectangle must fit
inside the image. Missing/duplicate/unknown fields, invalid roles and out-of-bounds
requests return 400; stale revision returns 409; missing job returns 404.

Returns an unresampled RGB PNG with `X-Fidelis-Revision`, `X-Fidelis-Crop` and
`Cache-Control: no-store`. Existing localhost Host/Origin/client checks apply.
The read-only artifact mapping is checksum/revision validated; only the bounded
crop is copied/encoded, not a full image-sized RGB buffer. Integrity checking can
still read the complete artifact. No hard latency or total-process memory target
is certified. No model inference or remote upload is involved.

## Evidence

HTTP/NumPy tests verify exact bytes for all three roles, protected pixels,
oddsized originals whose overview is decimated, last-pixel crops, invalid queries,
stale pairs, deletion and origin checks. Node tests exercise the actual geometry
and pair loader plus the inline editor with a DOM fixture: both images ready,
100/200% CSS size, divider alignment, unsaved-state retention, selection reset and
failed-pair hiding. These are protocol/DOM-contract tests, not actual browser
rendering, touch or target-device visual acceptance. F08-B remains open.
