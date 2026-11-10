# Persistent regional review

Start the existing studio with the project interpreter:

```bash
.venv/bin/python scripts/web-ui.py --bind 127.0.0.1 --port 8765
```

Open `http://127.0.0.1:8765/regions`, or use **Open saved regional review** in the
restoration studio. Import a precision base PNG, an aligned generated candidate
PNG, and the explicit NPZ masks described in [REGION_REBLEND.md](REGION_REBLEND.md).
This screen does not generate either pass or automatically classify regions.

Choose a starting profile, save the job, adjust skin/hair/fabric balance and save a
new blend revision. Compare the base and final image with the comparison slider,
or inspect the raw candidate separately. Download exports the full-resolution RGB
PNG; preview images are reduced to roughly one megapixel. Saved jobs reopen from
the selector after a server restart. A strict packshot job rejects nonzero generated
blend. An edit based on a stale revision is rejected rather than overwriting new work.

## Artifact contracts

Each manifest has schema version 1, a job ID, revision, dimensions, blend, profile,
timestamps, and immutable artifact descriptors (path, SHA-256, shape, dtype,
encoding, byte count). Base/texture/master are uint8 sRGB RGB. Masks are aligned
float32 `[0,1]` arrays. Unknown regions and missing confidence preserve the base.
External candidates explicitly have unknown backend/seed metadata; Fidelis does
not invent their generation recipe. Execution records are unsigned.

The SQLite ledger commits manifests only after new artifact files have been written.
Reblend candidates have unique paths; current manifests retain previous artifacts
until commit. Startup and the next write remove abandoned/unreferenced arrays.
Checksum failures reject rendering/export before using the affected artifact.
Explicit deletion reclaims saved jobs. This version provides process-restart
recovery; power-loss durability and disk corruption recovery are not certified.

## Resource limits

Defaults: 2 GiB of artifact storage, 32 MiB allowance for composition stripe
intermediates, and 40 million input pixels. Configure them when starting the studio:

```bash
.venv/bin/python scripts/web-ui.py --bind 127.0.0.1 \
  --region-workspace /path/to/fidelis-jobs \
  --region-disk-mib 2048 --region-workspace-mib 32 \
  --region-max-pixels 40000000
```

The default job directory is `.cache/web_outputs/region_jobs`. It is excluded from
version control. The storage cap includes the headroom required to retain old
artifacts while staging a new revision. Exceeding it leaves saved work intact;
delete an old job or increase the cap. SQLite database/journal bytes are outside
this artifact cap. No automatic eviction silently removes saved jobs.

Composition uses read-only disk mappings and row strips; PNG export encodes
scanlines without a full-frame Pillow copy. The stripe budget is an allocation
allowance, **not a measured total-process RSS guarantee**: mapped disk pages,
upload decoding, NumPy validation, Python, SQLite and codec overhead are separate.
Browser upload is capped at 34 MiB combined files (48 MiB JSON request). Imports
still decode images/masks in memory. Large production imports need the later
streaming ingest work; this does not certify an 8GB M1's full 8K working set.

## Local HTTP API

- `GET /api/regions/jobs`: jobs and profile defaults.
- `POST /api/regions/jobs`: base/texture PNG and mask NPZ as base64, profile, label.
- `GET /api/regions/jobs/{id}`: current public manifest.
- `POST /api/regions/jobs/{id}/reblend`: `expected_revision`, `blend` object.
- `GET /api/regions/jobs/{id}/preview?role=base|texture|master`: bounded preview.
- `GET /api/regions/jobs/{id}/export`: streaming full-size master PNG.
- `POST /api/regions/jobs/{id}/delete`: explicit workspace deletion.

Image requests can carry `revision=N`; a mismatched revision returns 409. POSTs
require JSON, reject cross-origin requests, and only accept localhost Host headers.
No arbitrary filesystem paths or download URLs are accepted. These routes are
single-user local tools, not an authenticated public deployment. The existing
restoration server's other routes are unchanged; bind the whole app to loopback.

## Current boundaries

The review screen supplies persistence, sliders, comparison and export. Brush
painting, undo/redo, automatic segmentation, asynchronous inference and calibrated
presets are later tasks. Saves run synchronously; no p95 latency target is claimed.
JavaScript syntax and real HTTP flows have been tested; visual browser review was
blocked by the review browser's connection to the local execution server.
