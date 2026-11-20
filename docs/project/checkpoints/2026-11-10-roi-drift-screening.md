# Structural ROI protection & drift screening checkpoint · 2026-11-10

## Scope and delivery

F10 / MEL-64 groundwork, based on `f84287993c9bc213dc47859b297a5a275381101d`
(`origin/feat/region-aware-studio`). Isolated branch:
`work/mel-64-roi-drift-screening` (`--no-track`). Parent `F10` stays `In Progress`
(`partial`) until evaluated on real F06 texture outputs and the cleared 60-case
`F12` ROI corpus. Remote Linear `MEL-64` sync remains pending.

## Implemented result

- Added `fidelis/postprocess/roi_protection.py` compatible with `fidelis/eval/corpus_manifest.py`
  ROI contracts (`id`, `kind`, `policy`, `rect`, plus explicit `override: "lock" | "unlock"`).
- Implemented `build_roi_protection_masks`: enforces explicit override precedence
  (manifest/default `preserve` -> `override="unlock"` -> `override="lock"` ->
  monotonic preservation of existing user `protected` masks) and optional bounded
  secondary Sobel `edge_guard` attenuation (`sobel_is_semantic_proof=False`).
- Implemented `screen_internal_drift`: enforces identical dimensions (rejecting
  implicit resizing), screens block-grid and per-ROI integer displacements and edge
  coherence, creates `drift_guard_mask`, and checks bit-exact pixel locking when a
  composed `master` is provided.
- Added CLI tool `scripts/screen-roi-drift.py` exporting compatible `.npz` masks
  (`protected`, `edge_guard`, `drift_guard`) and JSON drift reports with
  `--fail-on-drift`.
- Documented contract in `docs/ROI_DRIFT_SCREENING.md` and added 4 regression tests
  in `tests/test_roi_protection.py`.

## Verification

- `.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v`: passes
  all 125 baseline tests plus 4 new F10 ROI/drift tests (**129 total tests**).
- `tests/test-web-ui.sh`, `tests/smoke-test.sh`, `tests/test-detect-drift.sh`,
  `json.tool`, `py_compile`, and `git diff --check` verified after final edits.

Tests use controlled synthetic images and shifted interior blocks; live generative
candidate quality, OCR text checks, and cleared production ROI benchmarks remain open.

## Remaining limits and next action

- Connect `screen-roi-drift.py` / `screen_internal_drift` onto live F06 ComfyUI
  candidates and cleared F12 ROI cases once workers and photography are available.
- Next independent work without GPU: `F11` (`MEL-65`) colour-managed/alpha/precision
  export groundwork, or `F08-B` (`MEL-80`) same-host browser/device visual acceptance.
