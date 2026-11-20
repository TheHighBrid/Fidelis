# Studio review UI polish · 2026-11-19

F15 / MEL-69 display and interaction polish, with F08 native inspection left
read-only. Base `26d80750a87a6232d439ea761967471fb384d42b` on
`feat/region-aware-studio`. Branch `work/bot06-studio-ui-krea-polish-20261119`.
The delivery SHA is the commit containing this receipt. Not merged, not released,
and not a visual or device acceptance.

## Result

Verified the launch gaps against `studio.html` before editing. The page already
had one overlay checkbox, a fixed 0.6 display alpha, brush size/hardness/opacity,
preview zoom, and the F08-A native crop panel below the canvas. It did not have
per-channel visibility, an overlay-strength control, a legend, crop nudging,
a docked inspector, a persistent job/revision chip, or a layout between the
780px stack and the wide two-column rail.

Added display-only mask controls: Protect, Skin, Hair and Fabric can be shown
or hidden, Shift-click solos a channel, and overlay strength scales the preview
from 0 to 1. Protection is drawn with a blue hatch after the editable colours.
Saving still sends the existing stroke list and blend weights. Hiding a channel
clears only its preview pixels.

The native inspector can dock beside the canvas from 1100px upward and pin below
the canvas on narrower widths. Arrow keys move the crop centre by one original
image pixel while Inspect is selected; Shift+arrows jump. A centre-pixel control
and hover readout sample browser-decoded RGB from the crop images already loaded
for that revision. The readout says when those pixels cannot be read. Preview
zoom remains labelled as the reduced overview.

The toolbar stays visible with the job label, revision, dimensions and unsaved
state. Export links sit together. Widths through 780px stack, 781–1099px use a
narrower rail, and the open dock follows the tested placement helper.

## Verification

- `.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v`
  - First run, before `pytest` was installed in this executor: **268 tests, 5 errors**.
    The errors were `ModuleNotFoundError: No module named 'pytest'` while importing
    `tests/e2e/test_tier1_features.py` through `test_tier5_adversarial.py`.
  - After installing that missing test dependency, the same command passed
    **263 tests in 59.962s**, exit 0. The five E2E modules import, and their
    pytest functions are not unittest cases. This matches the earlier discovery
    note that a unittest pass does not execute the standalone pytest E2E functions.
- `PATH="$PWD/.venv/bin:$PATH" bash tests/test-web-ui.sh` — `Web UI server tests passed.`
- `PATH="$PWD/.venv/bin:$PATH" bash tests/smoke-test.sh` — `Static smoke tests passed.`
- `git diff --check` — exit 0.
- `node --check` on `fidelis/studio/editor.js`, `inspection.js`, `review-ui.js`,
  `tests/review-ui.cjs` and `tests/native-inspection-ui.cjs` — exit 0.
- Headless Google Chrome 157.0.8103.50 on this Linux executor, bound to
  `127.0.0.1:8766`, using a synthetic 64×48 sRGB pair:
  - A protect stroke drew overlay alpha and remained in unsaved history after the
    Protect channel was hidden (`history` length stayed 1; displayed alpha became 0).
  - ArrowRight moved centre X from 32 to 33 and reloaded the saved crop.
  - Read centre pixel returned a native-crop RGB sentence that distinguishes the
    loaded crop from preview zoom.
  - At 1440px the open inspector was `side` and the document did not overflow
    horizontally. At 900px it was `tablet` / `sheet`. At 390px it was `stack`.
    The same overflow check passed at all three widths.

No paid call, live worker, physical Android/iOS device, or human visual signoff
was involved. The synthetic pair does not evidence restoration quality.

## Narrow reading order · follow-up

At widths through 780px the review stage and paint section, including the mask
legend, now come before the import form. Wider layouts keep the rail on the left
and the canvas on the right. Save, crop, and protection behaviour are unchanged.

Headless Google Chrome 157.0.8103.50 on this Linux host, still using the synthetic
64×48 pair and `127.0.0.1`:

- 390px: layout `stack`. Canvas top 230, mask legend top 1483, import form top
  2161. `scrollWidth <= clientWidth + 1`.
- 900px: layout `tablet`. Import stays in the left column, left of the canvas.
  The same overflow check passed. The open inspector remained `sheet`.
- 1440px: layout `desk`. Import stayed left of the canvas. The same overflow
  check passed. The open inspector remained `side`.

`node tests/review-ui.cjs` passed, including the narrow source-order sort.
`node tests/native-inspection-ui.cjs` passed. This is not device or visual
acceptance.

## Remaining

F08 and F15 stay in progress. Physical touch hardware, photographic visual
acceptance, and the external E2–E4 gates are unchanged. The narrow order is
implemented and headless-checked; it is not a physical-device signoff.
