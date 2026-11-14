# Colour-managed, straight-alpha and high-precision export checkpoint · 2026-11-10

## Scope and delivery

F11 / MEL-65 standalone export groundwork, branched cleanly (`--no-track`) from
`f84287993c9bc213dc47859b297a5a275381101d` (`origin/feat/region-aware-studio`) on
isolated branch `work/mel-65-managed-export`. Parent `F11` remains `In Progress`
(`partial`) until integrated into Studio HTTP/store upload & download paths and
evaluated with live `F06` outputs and `F10` structural ROI cases. Remote Linear
`MEL-65` sync remains pending.

## Implemented result

- Added `fidelis/postprocess/managed_export.py` extending `regions.py` profiles
  with EXIF orientation (`1..8`) normalization, straight-alpha preservation (RGBA),
  validated LittleCMS / `float64` Matrix-TRC ICC conversions (`preserve`, `srgb`,
  `custom`), true `uint16`/`float64` linear-light blending, lossless 8/16-bit PNG
  & TIFF encoders, explicit `container_precision_exceeds_source` anti-masquerading
  metadata, zero default synthetic grain (`grain_strength=0.0`), and bit-exact
  restoration of locked/zero-alpha base pixels after quantization.
- Added atomic round-trip-verifying CLI `scripts/export-master.py` outputting
  `.png` / `.tif` / `.tiff` masters and `.recipe.json` provenance sidecars.
- Documented contract in `docs/MANAGED_EXPORT.md` and added 6 fixture/CLI tests in
  `tests/test_managed_export.py` (including an OpenCV 8-bit TIFF premultiplication
  regression fix verified via Pillow straight-alpha reading).

## Verification

- `.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v`: passes
  all 125 baseline tests plus 6 new F11 managed-export tests (**131 total tests**).
- `tests/test-web-ui.sh`, `tests/smoke-test.sh`, `json.tool`, `py_compile`, and
  `git diff --check` verified after final edits.

Tests use synthetic 8/16-bit PNG/TIFF images and synthetic RGB Matrix-TRC ICC
profiles; live `F06` outputs, Studio HTTP upload ingest of ICC/16-bit images, and
real display/printer visual review remain open.

## Remaining limits and next action

- Connect optional managed-export options into PR #12 Studio `/regions` export
  and native job artifacts once PR #12 merges and `F10` ROI gates progress.
- Keep `F11` `In Progress` (`partial`) until Studio upload/download ingest and
  live/device acceptance complete.
