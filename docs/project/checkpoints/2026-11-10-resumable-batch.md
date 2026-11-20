# Resumable bounded batch processing checkpoint · 2026-11-10

## Scope and delivery

F14 / MEL-67 standalone coordinator and CLI groundwork, branched cleanly
(`--no-track`) from `f84287993c9bc213dc47859b297a5a275381101d`
(`origin/feat/region-aware-studio`) on isolated branch
`work/mel-67-resumable-batch`. Parent `F14` moves from `Backlog` to `In Progress`
(`partial`) until connected to qualified live `F06` workers and `F11` Studio
exports on target hardware. Remote Linear `MEL-67` sync remains pending.

## Implemented result

- Added `fidelis/studio/batch.py` (`BatchRunner`, `BatchItemContext`) reusing
  existing `canonical_hash`, `sha256`, `SubmissionUnknown`, and `BudgetExceeded`
  contracts: single-owner `fcntl.flock` lock, SQLite persisted item recipes and
  deterministic `run_id`, startup crash recovery (`interrupted` vs
  `needs_review`), zero duplicate paid submission on resume/retry, bounded
  `ThreadPoolExecutor(1..4)` workers, strict `disk_budget_bytes` and
  `cost_budget_usd` checks, source/output SHA-256 verification, and full
  `attempt_history` visibility.
- Added CLI `scripts/batch-run.py` (`enqueue`, `run`, `status`) with explicit
  `packshot_verify` / `deterministic_bicubic` offline handlers and atomic
  `.recipe.json` provenance sidecars (`unsigned_execution_record`).
- Documented contract in `docs/BATCH_PROCESSING.md` and added 4 regression tests
  in `tests/test_batch_runner.py` (crash recovery, paid-work lock, bounded
  workers, disk/cost budgets, tamper/loss detection, and end-to-end CLI).

## Verification

- `.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v`: passes
  all 125 baseline tests plus 4 new F14 batch tests (**129 total tests**).
- `tests/test-web-ui.sh`, `tests/smoke-test.sh`, `json.tool`, `py_compile`, and
  `git diff --check` verified after final edits.

Tests use mock workers and offline PNG fixtures; live GPU batch execution and
measured sustained hardware thermal/memory telemetry remain open.

## Remaining limits and next action

- Wire qualified `F06` texture workers and `F11` managed export pipelines into
  `BatchRunner` worker callbacks once `M1`/`M2` prerequisites land and qualify.
- Keep `F14` `In Progress` (`partial`) until live resumable production batch runs
  complete.
