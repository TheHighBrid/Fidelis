# Corpus rights & ROI manifest checkpoint · 2026-11-10

## Scope and delivery

F12-A / MEL-79, based on `c15d10d49bd3c2baae23c2bd9e27a5fa3cd3f328`
(`origin/feat/region-aware-studio`). Isolated branch:
`work/mel-79-corpus-roi-manifest` (`--no-track`). Schema/inventory work requires no
GPU weights or model execution; remote PR review and Linear `MEL-79` sync remain
pending. Parent `F12` (`MEL-63`) retains cleared photo acquisition, comparator
execution, and frozen 60-case population.

## Implemented result

- Added `fidelis/eval/corpus_manifest.py` defining schema v1, `CORPUS_CATEGORIES`
  (12 `portraits`, 12 `apparel_model`, 12 `textiles`, 12 `macros`, 12 `packshot_edge`),
  `build_template_manifest`, `measure_regression_assets`, and fail-closed
  `validate_corpus_manifest` / `load_corpus_manifest`.
- Created the committed frozen 60-slot manifest in `experiments/corpus_manifest.json`
  with exact 30 `calibration` / 30 `held_out` split (`6` per category per split),
  all 60 production slots marked `availability: "missing"` (`0/60` available), explicit
  `model_release_required` flags on portraits/apparel frames, planned `known_text`,
  and typed `critical_rois` requirements (`must_lock_base`, `roi_type`).
- Measured and recorded the 8 tracked PNG fixtures/crops (`tests/fixtures/*.png` and
  `experiments/eval_crops/*.png`) in `regression_assets` with their SHA-256 digests,
  dimensions, `counts_toward_60_case_corpus: false`, and `rights_cleared: false`.
- Added CLI validator `scripts/validate-corpus-manifest.py` (`--verify-files`, `--json`)
  to enforce consent/release clearance, path-traversal safety, disk SHA-256/dimension
  parity, non-empty normalized ROI bounds on available entries, and cross-split SHA
  isolation (blocking calibration/held-out contamination).
- Documented the contract in `docs/CORPUS_MANIFEST.md` and added 6 regression tests
  in `tests/test_corpus_manifest.py` wired into `.github/workflows/ci.yml`.

## Verification

- `.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v`: covers
  all 102 existing Studio/pipeline tests plus 6 new manifest validation/CLI tests
  (**108 total tests**).
- `.venv/bin/python scripts/validate-corpus-manifest.py --verify-files`: verifies
  `0/60` available (`0/30 calibration`, `0/30 held_out`, `60 missing`) and `8/8`
  tracked regression assets on disk.
- `tests/test-web-ui.sh`, `tests/smoke-test.sh`, `json.tool`, `py_compile`, and
  `git diff --check` verified after final edits.

These checks verify manifest structure, rights/ROI invariants, and hash/dimension
verification on disk. No licensed Studio production photographs were committed, and
no model benchmark/comparator quality score was run.

## Remaining limits and next action

- Acquire licensed/consented 60-case photography (`0/60` currently available), populate
  cleared `source` + normalized `[x0, y0, x1, y1]` `critical_rois`, and re-run
  `scripts/validate-corpus-manifest.py --verify-files` under parent `F12`.
- Continuing independent work: `F05-B` (`MEL-75` candidate model hashes/usage terms),
  `F08-B` (`MEL-80` same-host browser/device visual acceptance), and `F05-A` / `F06`
  when compatible local weights/workers are configured.
