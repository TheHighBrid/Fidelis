# Native inspection checkpoint · 2026-11-10

F08-A / MEL-78, based on `e0a8602480e58237325b2d6f9848e2c6ff2883ad`.
Implementation used isolated branch `work/mel-78-native-inspection`; delivery is in
Studio PR #12. The delivery SHA is the commit containing this receipt. In Review,
not merged/released; parent F08 still requires browser/device acceptance.

## Result

Added bounded, revision-pinned native RGB crop responses for base/texture/master.
The read-only inspector compares the same rectangle/revision at 100% and 200%
CSS pixel scaling, with coordinate inputs, overview selection, 128/256/512 crop
sizes and scrolling on narrow layouts. Caption distinguishes saved original pixels
from the overview. Pixelated 200% rendering adds no invented image detail.

Both images must decode at matching dimensions before display. A newer selection,
closed panel or changed job invalidates prior loads; failed/stale pairs remain
hidden. Inspection does not reset unsaved strokes, modify blends or submit inference.
Existing preview painting and streaming full-resolution export remain intact.

## Verification

Full Python discovery: **102 tests passed**, including 10 native-inspection tests.
Existing web HTTP integration and static smoke passed. New inspection, existing
brush and inline editor JavaScript syntax passed; Python compilation and diff
checks passed. Documentation links, 27 task mappings/dependencies and YAML validated.

New tests compare exact pixel values from full-resolution arrays and returned
PNG crops, including protected master pixels, an odd-sized >1MP image with a
reduced overview, corner crops, rejected bounds/roles/query fields, stale revisions,
read-only persistence and origin checks. Node tests verify geometry/scaling and
paired sequencing, plus actual inline-editor DOM contracts for zoom/divider,
unsaved-state preservation, selection reset and failure handling.

No real browser rendering, pointer/touch device visual signoff, live GPU output,
M1/Android memory certification or competitive quality comparison was performed.
The DOM fixture is not a substitute for F08-B device acceptance. Crop allocations
are bounded; checksum I/O and total-process memory/latency remain unqualified.

## Next action

Review this implementation and perform F08-B on a reachable same-host browser and
target devices. Continue independent corpus/ROI preparation (F12-A) and qualify
confidence-gated masking (F09) against real data; unknown areas must remain base.
See the [inspector contract](../../NATIVE_INSPECTION.md) and updated status/backlog.
