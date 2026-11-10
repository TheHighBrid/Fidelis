# Local ComfyUI texture bridge

This is a protocol-tested adapter, not a shipped quality-certified SDXL/FLUX
workflow. It accepts a trusted, operator-supplied **exported API graph**, validates
it against the running worker, uploads an already-scaled precision base, submits
once, retrieves an aligned texture and optionally updates a saved regional job.
No checkpoint, LoRA, ControlNet or custom node pack is installed automatically.
No cloud provider or payment API is called by the adapter.

## Installation and readiness

Install the optional client dependency into the existing project environment:

```bash
.venv/bin/python -m pip install -r requirements-studio.txt
.venv/bin/python scripts/backend-doctor.py
```

The report distinguishes declared candidates, installed files, matched checksums,
NCNN executable presence, PyTorch importability and ComfyUI reachability. None of
these alone implies successful inference or accepted image quality. Model licenses
remain separate from file integrity.

Execution-environment audit on 2026-11-10: Linux x86_64; the three candidates in
`config/photo-candidates.tsv` were absent, the native NCNN executable was absent,
PyTorch was absent, `nvidia-smi` was absent, and no ComfyUI server responded at
`127.0.0.1:8188`. Cloud API keys were not configured. This is the development
executor's state, not a claim about the owner's Mac or tablet. Consequently no
live GPU inference or competitive-quality result was obtained.

## Workflow bundle

Wrap a working ComfyUI **API-format export** in a local JSON object with:

| Field | Value |
| --- | --- |
| `schema_version` | `1` |
| `family` | `sdxl`, `flux`, or `other` |
| `input_node` | String node ID of a `LoadImage` node |
| `output_node` | String node ID of a `SaveImage` node |
| `workflow` | Exported API graph object |

Retain the real checkpoint names, compatible conditioning/VAEs, sampler settings,
seed and generation parameters in that export. The adapter changes only the
configured LoadImage path after uploading. It does not assume SDXL and FLUX graphs
are interchangeable, map arbitrary sliders, infer missing model files, or resize
mismatched output. For the texture pass, the workflow must preserve the input's
exact dimensions and spatial registration; equal dimensions alone cannot prove
internal geometric fidelity.

A graph hash pins the supplied recipe, **not the worker's checkpoint bytes**.
Record and independently verify model hashes and worker/custom-node revisions
before quality promotion. A locally supplied graph may execute custom nodes; use
only a trusted local inference workflow. The bridge does not audit arbitrary node
code or authorize external paid API nodes.

No placeholder graph is shipped as a production preset. Doing so would disguise
missing weights and untested architecture as a completed enhancement engine.

## Execute and resume

Run an exported workflow against a pre-scaled base:

```bash
.venv/bin/python scripts/generate-texture.py workflow-bundle.json texture.png \
  --source base.png
```

Or apply the candidate to an existing regional job after generation:

```bash
.venv/bin/python scripts/generate-texture.py workflow-bundle.json texture.png \
  --workspace .cache/web_outputs/region_jobs --job JOB_ID
```

The job's masks and blend weights are retained. A changed job revision prevents
replacement, leaving the generated texture available separately. Packshot Strict
rejects generation entirely. Output must be untagged, orientation-normalized RGB
PNG on the exact base grid.

The CLI derives a stable run UUID from source/recipe/address unless `--run-id` is
explicitly supplied. It prints that ID before submission. Repeating the same
command resumes that run or reuses its verified cached output. Change seed or use
a new UUID only when intentionally requesting a new generation.

`--deadline` limits polling time (default 300 seconds); individual HTTP calls have
their own timeout. Pending runs remain submitted in SQLite and can be polled later.
No global `/interrupt` call is sent, because it could stop another user's job.
Cancellation and a fully asynchronous worker queue remain F07 work.

## Failure handling and persistence

States include preparing, submitting, submitted, completed, failed, rejected,
preparation_failed and submission_unknown. Reservation precedes `/prompt`.
An ambiguous timeout/5xx does not trigger another submission. The adapter searches
queue/history metadata for the same request marker and resumes only if one unique
prompt ID is found. Missing/expired history is not proof that no job ran; unresolved
runs require inspection instead of automatic resubmission. Preparation failures
are retained as terminal records in this first adapter.

Saved records contain source/recipe hashes, workflow graph, dimensions, prompt ID,
state and output checksum. Cached files are hash-checked. Records explicitly mark
`live_quality_verified: false`. The adapter cannot detect arbitrary internal object
warping; visual/ROI quality checks and model compatibility certification remain
mandatory before production promotion.

The backend accepts loopback HTTP only. An explicitly configured SSH tunnel can
connect to a separate GPU worker without silently uploading to an external service.
HTTP proxy inheritance and redirects are disabled. Responses have byte limits.

## Validation evidence

The protocol fixture uses a deliberately named `FixtureTexture` node and fixed
pixels. It verifies real HTTP request/response behaviour, not model inference.
Tests cover cache reuse, uncertain-submission reconciliation, timeout resume,
execution errors, missing nodes, cyclic graphs, dimension rejection and protected
regional-job replacement. Brush tests independently cover native strip boundaries,
confidence routing, exact protected output and browser/native brush parity.

Primary API references checked 2026-11-10:

- https://docs.comfy.org/development/comfyui-server/comms_routes
- https://github.com/Comfy-Org/ComfyUI/blob/master/server.py
- https://github.com/Comfy-Org/ComfyUI/blob/master/script_examples/basic_api_example.py
