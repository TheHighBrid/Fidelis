# Background local texture generation

F07-A adds an opt-in, single-worker queue to the existing regional editor. It uses
the existing ComfyUI adapter and its durable run ledger. This is fixture/protocol
verified orchestration, not model quality acceptance or a public multi-user service.

## Enable explicitly

Prepare a trusted exported workflow bundle as described in
[the adapter contract](COMFY_TEXTURE_BACKEND.md), then start:

```bash
.venv/bin/python scripts/web-ui.py --bind 127.0.0.1 \
  --texture-workflow /absolute/path/workflow-bundle.json \
  --comfy-address http://127.0.0.1:8188 \
  --generation-root .cache/async_generation
```

Without `--texture-workflow`, generation is disabled. Opening the editor never
submits a prompt. Browser requests cannot select an arbitrary workflow, address,
filesystem source or output destination. The startup graph is trusted operator
configuration; custom/API nodes still require independent review of their behaviour.

Open `/regions`, import aligned passes and save edits. Select **Generate local
candidate**. A successful candidate replaces the texture and recomposes against
saved masks only if the saved revision is unchanged. Reload the saved revision to
inspect the result. The editor deliberately does not overwrite unsaved strokes
when a background task completes. Packshot Strict rejects generation.

## Task and cancellation contracts

| State | Meaning / action |
| --- | --- |
| queued | Persisted locally, waiting for the single worker |
| running | Worker preparing, submitting, reconciling or polling the same run ID |
| applying | Atomic revision-checked result commit has started; cancellation returns conflict |
| completed | Candidate committed; result revision recorded |
| waiting | Poll deadline reached; explicitly resume the existing run |
| needs_review | Submission cannot be confirmed; resume attempts reconciliation, never automatic resubmission |
| interrupted | Worker stopped/restarted; explicitly resume to reconcile the existing run |
| failed | Error or stale/deleted job prevented application; inspect before intentionally starting another task |
| cancelled | Local task abandoned; it cannot apply a late result |

**Cancellation is local abandonment.** Submitted GPU work may continue in ComfyUI.
No global `/interrupt`, queue clear or pending-prompt deletion is issued. The
response/editor disclose remote continuation. Cancellation before the local worker
claims a never-submitted task sends no model request. Cancellation is scoped to the
job/task pair, not to arbitrary remote prompt IDs. It is not multi-tenant identity
authorization; the server remains loopback-only.

The application decision is serialized with cancellation. Cancellation that wins
before `applying` prevents application. Once `applying` wins, cancellation returns
409 and the revision-safe commit finishes. This boundary keeps status reads
responsive while the image store renders/commits. Any intervening job edit or
deletion fails closed instead of overwriting it.

## Durability and limits

The directory contains `queue.sqlite3`, a process ownership lock and the existing
backend run/cache directory. Exactly one queue owner may use that directory.
Default capacity is four queued/running/applying tasks, with 64 retained records.
Unresolved tasks prevent a second task for the same job. Terminal records count
toward the record cap; there is no automatic pruning/retention policy yet. Hitting
a cap returns an explicit error rather than silently dropping history.

One worker decodes/runs a job at a time. A second claim is refused while that
task is in flight, and a second worker thread is refused for the same queue.
The directory lock still allows only one process owner. Polling defaults to 300 seconds; HTTP
calls use two-second connect/read timeouts. These are cooperative timeouts, not a
certified end-to-end latency bound. Image decoding, downloads, rendering and
process memory still need target-device measurement. The backend response limit
is 200 MiB per output. The existing JobStore byte budget does not include the
separate generated PNG cache; aggregate cache retention/quota is still release
work. Do not infer an 8GB/8K memory guarantee from queue capacity.

On restart, untouched queued work can execute. Former running/applying tasks become
`interrupted` and require explicit resume. Resume retains the source revision,
bundle, backend address and run ID. A changed address is rejected. A crash during
application can leave the job already committed; a resumed stale revision fails
closed, and the saved job/ledger must be inspected. Exactly-once automatic apply
reconciliation across those two databases is not claimed. A lost/expired ComfyUI
history entry never authorizes a replacement prompt.

Task updates use one SQLite transaction (`BEGIN IMMEDIATE`, `synchronous=FULL`).
A failed transaction does not publish a partial row. An empty, truncated, or
non-SQLite `queue.sqlite3` raises `QueueStorageError` and is left byte-for-byte
in place; the queue does not create a replacement database over it. A readable
database whose task JSON is damaged or missing required fields is rewritten to
`needs_review` with `quarantined` set, `error` `CorruptRecord`, and
`remote_may_continue` true. That row is not executed and cannot be resumed.
It still owns its job until an explicit cancel. The SHA-256 of the rejected
bytes is kept on the row; the raw payload is not copied into the record.

Cancellation tokens are read through a queue-owned signal collaborator. A
retired token raises `PermissionError` or `RuntimeError`. That failure does not
clear a cancellation already stored in SQLite, and it does not by itself cancel
a task whose durable flag is false. After the durable flag is set, a late
applicable receipt does not change the job revision. An unexpected worker
exception leaves `running` or `applying` as `interrupted` and the worker keeps
serving later tasks. Restart is what marks in-flight rows when the process
itself exits.

The queue module does not download runtimes or open a non-loopback address.
Offline bundles must include `fidelis/studio/cancellation.py` with
`fidelis/studio/generation.py`. `scripts/package-offline-bundle.sh` does not
invoke `scripts/install-macos-runtime.sh`; that installer remains the
network-backed native NCNN path and is outside this queue.

Shutdown stops polling cooperatively, preserves the existing run and waits for the
worker before releasing ownership. It does not cancel remote GPU execution.

## Local API

All routes inherit regional Host/Origin/client-loopback checks and JSON limits.

| Method | Route suffix after `/api/regions/jobs/{job_id}` | Result |
| --- | --- | --- |
| POST | `/generations` | `expected_revision` integer; returns 202 plus task/run identity |
| GET | `/generations` | Persisted task summaries for that job |
| GET | `/generations/{task_id}` | Current task summary |
| POST | `/generations/{task_id}/cancel` | Cancel local work; remote-continuation disclosure |
| POST | `/generations/{task_id}/resume` | Explicitly queue reconciliation/polling of the same run |

The jobs listing includes `generation_enabled`. Disabled generation returns 503;
wrong job/task pairs return 404; stale/conflicting transitions return 409; queue or
record bounds return 413. Task summaries exclude the configured graph/address.
No websocket progress percentage or GPU timing is fabricated.

## Verification and remaining acceptance

`tests/test_generation_queue.py` uses a real HTTP fixture with fixed pixels and a
`FixtureTexture` node. It covers successful protected composition, bounds, job
ownership, queued/running cancellation, late results, commit races, restart,
explicit reconciliation, polling timeout, stale revisions, process ownership,
HTTP responsiveness/origin checks and actual optional-worker server startup.

F07 live acceptance still requires a compatible worker/model and operational
review. Native crop inspection, browser/device visual acceptance, cache quotas and
release packaging remain separate work.
