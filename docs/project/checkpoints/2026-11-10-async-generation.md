# Background generation checkpoint · 2026-11-10

## Scope and delivery

F07-A / MEL-77, based on `2c55c79a36bed64f7b8e459b9bc885311afc8141`.
Isolated implementation branch: `work/mel-77-async-jobs`; integrated into Studio
PR #12. Delivery SHA is the commit containing this receipt. In Review, not merged
or released. Parent F07 retains its live worker/quality acceptance gate.

## Implemented result

- Opt-in trusted startup workflow and loopback backend; no browser-selected graph,
  remote upload fallback, model installation or opening-page inference.
- Durable SQLite task IDs mapped to stable backend run IDs, four-slot queue,
  one process owner/worker and 64 retained records by default.
- HTTP 202 enqueue, scoped status/cancel/resume and editor controls with persistent
  status and explicit local-only cancellation disclosure.
- Queued work survives restart; interrupted work requires explicit resume.
  Poll deadlines and uncertain transport/submission preserve the existing run;
  no ambiguous automatic duplicate submission.
- Cancellation before apply wins over a late result. At `applying`, cancellation
  conflicts while the revision-safe commit finishes. No global interrupt or queue
  mutation is issued, so unrelated prompts remain untouched.
- Saved masks/protected pixels survive successful candidate application. Changed
  revisions or deleted jobs fail closed. Unsaved browser strokes are never replaced
  automatically by a completed result; reload remains explicit.

## Verification

The final full Python discovery passed **92 tests**, including 15 queue tests.
Existing HTTP web UI and static smoke checks passed. Both regional editor scripts
passed Node syntax checks; Python compilation and diff checks passed. Documentation
link/backlog validation passed. The queue regression suite includes actual server
startup plus HTTP responsiveness, ownership/capacity, late cancellation, commit
boundary, stale revisions, queued/interrupted restart, transport failure and
same-run reconciliation without duplicate submission.

These are controlled executable/protocol tests. The fixture returns fixed pixels
through a `FixtureTexture` node; it does not run a diffusion model. Remote CI,
visual browser/touch acceptance, live GPU quality, M1/Android memory and deployment
acceptance were not performed. No paid inference or model download was used.

## Remaining limits and next action

Read the [queue contract](../../ASYNC_GENERATION.md) for states, setup and limits.
Local cancellation does not stop submitted GPU computation. Crash during apply
can require saved-job/ledger inspection; cross-database automatic exactly-once
apply recovery is not claimed. Backend PNG-cache aggregate quotas/pruning and
target-device memory/latency certification remain release work. The server remains
local and single-user. The independent next implementation is F08-A native-pixel
crop inspection; actual F05/F06/F07 live acceptance needs compatible weights and
worker access. Review this delivery before marking MEL-77 Done.
