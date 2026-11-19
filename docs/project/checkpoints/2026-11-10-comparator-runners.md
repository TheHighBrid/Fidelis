# Comparator runners & blind pairwise review checkpoint · 2026-11-10

## Scope and delivery

F12 / MEL-63 reproducible comparator runners and blind pairwise/bootstrap scoring
groundwork, branched cleanly (`--no-track`) from
`f84287993c9bc213dc47859b297a5a275381101d` (`origin/feat/region-aware-studio`) on
isolated branch `work/mel-63-comparator-runners`. Parent `F12` remains
`In Progress` (`partial`) until all 60 production corpus assets are cleared/frozen
and actual comparator runs (selected base, Fidelis, VOSR challenger, Clarity, Krea)
plus real blind human reviews execute. Remote Linear `MEL-63` sync remains pending.

## Implemented result

- Added `fidelis/eval/comparators.py` reusing `corpus_manifest.py` (`verify`,
  `audit`, `inspect_image`, `digest`, `local_path`) and `pipeline_metrics.py`
  (`measure_pipeline_metrics`):
  - Enforces single-image full-resolution outputs per comparator per case (never
    contact sheets or collages), target-dimension matching without silent
    resizing, and `rights.remote_processing == "allowed"` blocking on remote
    comparators (`pinned_clarity`, `dated_krea`).
  - Includes built-in `interpolation_runner` (Lanczos3), pre-rendered output +
    disclosure sidecar importer (`make_imported_output_runner`), honest
    `"unavailable"` / `"skipped_remote_disallowed"` / `"failed"` status
    accounting without simulated scores or dropped failure denominators.
  - Generates blind randomized A/B pairwise ballots (`build_blind_pairwise_manifest`)
    with separate answer key (`blind_key.json`) and computes category minimums,
    win / preference+tie rates, 95% bootstrap confidence intervals, critical defect
    blocking, and `n < 100` preliminary flags (`summarize_blind_reviews`).
- Added CLI `scripts/run-comparators.py` (`run`, `summarize-blind`) and documented
  contracts in `docs/COMPARATOR_RUNNERS.md`.
- Added 4 regression tests in `tests/test_comparators.py` covering locked
  60-case synthetic runs, tracked regression inventory handling (`target_dimensions=null`),
  remote permission blocks, dimension mismatch refusal, and blind scoring gates.

## Verification

- `.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v`: passes
  all 125 baseline tests plus 4 new F12 comparator tests (**129 total tests**).
- `tests/test-web-ui.sh`, `tests/smoke-test.sh`, `json.tool`, `py_compile`, and
  `git diff --check` verified after final edits.

Tests use synthetic pixels, mock comparators, and the tracked 8-case regression
inventory; no live external comparator APIs or production photographs ran.

## Remaining limits and next action

- Populate and freeze the cleared 60-case production corpus (`F12-A` / `F12`), run
  real local/licensed comparators on `calibration` then `held_out`, and record blind
  human evaluations for `F13`.
