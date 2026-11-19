# Resumable bounded batch processing (`F14` / `MEL-67`)

This groundwork adds a durable SQLite-backed, single-owner batch coordinator
that persists per-image recipes, deterministic `run_id` identities, byte/cost
budgets, and retry history across interrupted runs without duplicating committed
paid/remote submissions.

## Modules and CLI

- Coordinator: [`fidelis/studio/batch.py`](../fidelis/studio/batch.py) (`BatchRunner`, `BatchItemContext`)
- CLI: [`scripts/batch-run.py`](../scripts/batch-run.py) (`enqueue`, `run`, `status`)
- Regression suite: [`tests/test_batch_runner.py`](../tests/test_batch_runner.py)

## Key invariants

1. **Zero duplicate paid work on resume.** Items that reach
   `ctx.mark_paid_submitted()` or encounter `SubmissionUnknown` transition to
   `needs_review` after crashes or timeouts. `run(retry_failed=True)` never
   automatically re-submits `needs_review` items; callers must supply a read-only
   `reconcile_fn` keyed by the persisted `run_id`.
2. **Startup crash recovery & single-owner lock.** `BatchRunner` holds a
   non-blocking `fcntl.flock` on `batch.lock`, cleans orphaned temp files in `.tmp/`,
   marks pre-commit interrupted `running` rows as `interrupted`, and verifies
   `output_sha256` on previously `completed` items so deleted/corrupted files are
   surfaced visibly rather than silently skipped or overwritten.
3. **Bounded memory, workers, disk and spend.** Concurrency is capped to
   `max_workers` (`1..4`), items stream by file path rather than holding batch
   arrays in memory, and pre-dispatch / pre-commit checks fail excess items with
   `BudgetExceeded` when `disk_budget_bytes` or `cost_budget_usd` is reached.
4. **Visible attempt history & unsigned provenance.** Every failed attempt and
   bounded retry (`retry_count <= max_retries`) appends timestamped outcome
   details to `attempt_history`, and completed items emit atomic
   `<output>.recipe.json` records (`provenance: "unsigned_execution_record"`).

## Usage

```bash
.venv/bin/python scripts/batch-run.py enqueue \
  --batch-dir .cache/batch_run1 --input-dir ./in --output-dir ./out \
  --handler packshot_verify --max-workers 2 --disk-budget-mib 1024

.venv/bin/python scripts/batch-run.py run --batch-dir .cache/batch_run1 --retry-failed
.venv/bin/python scripts/batch-run.py status --batch-dir .cache/batch_run1
```

## Boundaries

Offline CLI handlers currently provide `packshot_verify` and explicit
deterministic baseline `deterministic_bicubic`; connecting live `F06` ComfyUI
workers and `F11` managed exports inside production batch pipelines remains open
until those prerequisites qualify.
