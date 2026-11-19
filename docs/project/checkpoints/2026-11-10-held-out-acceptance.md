# Held-Out Quality Acceptance Protocol Checkpoint · 2026-11-10

- **Issue / Task**: `F13` (`MEL-66` — Calibrate and pass held-out quality acceptance)
- **Branch**: `work/mel-66-held-out-acceptance` (based on `origin/feat/region-aware-studio` `f84287993c9bc213dc47859b297a5a275381101d`)
- **State**: `In Progress` (`implementation: "partial"`)

## Summary of Changes

1. **Held-Out Quality Acceptance Evaluator (`fidelis/eval/quality_acceptance.py`)**:
   - Implemented `evaluate_held_out_acceptance`, `validate_reproducibility_receipt`, `wilson_95_ci`, and `bootstrap_95_ci`.
   - Enforces frozen calibration recipe, split isolation between `calibration` and `held_out` cases, zero critical fidelity defects, `>= 80%` preference-plus-ties and `>= 50%` win rate per comparator target, `>= 60%` preference-plus-ties and 6 distinct held-out cases per category across all 5 categories, and explicit `owner_creative_signoff` gating (`awaiting_owner_signoff` vs `accepted`).
2. **CLI & Unit Tests (`scripts/evaluate-quality-acceptance.py`, `tests/test_quality_acceptance.py`, `.github/workflows/ci.yml`)**:
   - Added CLI with `--output` and `--require-owner-signoff`.
   - Added 4 unit tests covering Wilson CI bounds, quantitative gate pass + owner signoff transition, fail-closed rejection on critical defects / split contamination / category drop, and CLI exit codes.

## Verification Results

- `.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v`: **129 tests passed** (125 baseline + 4 new `test_quality_acceptance.py` tests).
- `PATH="$PWD/.venv/bin:$PATH" bash tests/test-web-ui.sh`: passed.
- `PATH="$PWD/.venv/bin:$PATH" bash tests/smoke-test.sh`: passed.
- `git diff --check`: clean.

## Remaining Gate for Full `F13` Completion

- Cleared 60-case production corpus assets, live Clarity/Krea comparator outputs, human blind review ballots, and final owner creative signoff remain external gates; `F13` stays `In Progress` (`partial`).
