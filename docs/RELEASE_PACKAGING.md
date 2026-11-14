# Release Packaging & Workspace Upgrade/Rollback Protection (`F15` / `MEL-69`)

Fidelis Studio packages must include all required Studio (`fidelis/studio`),
postprocessing (`fidelis/postprocess`), evaluation (`fidelis/eval`), and benchmark
protocol (`config/benchmark`) modules while strictly excluding local user workspaces
(`.cache`), virtual environments (`.venv`), credentials (`.env*`), and unmerged build
outputs.

Across version upgrades and rollbacks, saved regional jobs (`JobStore` in
`.cache/web_outputs/region_jobs`) and durable generation run ledgers
(`GenerationRunStore` in `.cache/generation_runs`) must remain intact and
byte-verified.

## 1. Release & Offline Bundle Packaging

- `scripts/package-release.sh` builds `dist/fidelis-v<version>.tar.gz` (and `.zip`
  when `zip` is available) with `.sha256` checksums, excluding `.cache`, `.fidelis`,
  `.venv`, `.git`, `runtime`, `models`, `.env*`, and audition/corpus output folders.
- `scripts/package-offline-bundle.sh` builds air-gapped bundles with the same
  exclusions.
- `Dockerfile` installs both `requirements.txt` and `requirements-studio.txt`, and
  `.dockerignore` prevents local `.cache`, `.venv`, and `.env*` files from entering
  container build contexts.

## 2. Archive Auditing & Workspace Snapshot CLI

For a zero-additional-cost local preview, build the two source archives from a
specific committed tree:

```bash
bash scripts/package-local-preview.sh "$(git rev-parse HEAD)" ../fidelis-preview
```

Choose a new output directory. The builder reads the Git commit directly, audits
both archives, and writes a separate receipt with the source SHA, builder
versions, and verified archive checksums. For byte-for-byte comparisons use the
same Python and zlib build. The preview bundles no models or native runtimes.
Use the [onboarding](../ONBOARDING.md) dependencies and the existing local NCNN
runtime with the provenance-pinned RealeSR-general-v3 model for inference.
Preview filenames and receipts are distinct from the official v3.1.0 manifest
and do not change the production acceptance gates.

Use `scripts/verify-upgrade-rollback.py` (backed by `fidelis/studio/packaging.py`) to
audit release archives and protect user workspaces before upgrading or rolling back:

```bash
# 1. Audit a release archive or offline bundle
.venv/bin/python scripts/verify-upgrade-rollback.py audit-archive dist/fidelis-v3.0.0.tar.gz
.venv/bin/python scripts/verify-upgrade-rollback.py audit-archive --strip-top-level dist/fidelis-offline-bundle-v3.0.0.tar.gz

# 2. Verify live workspace integrity (SQLite schema, job manifests, .npy SHA-256 digests)
.venv/bin/python scripts/verify-upgrade-rollback.py verify-workspace \
  --region-root .cache/web_outputs/region_jobs \
  --generation-root .cache/generation_runs

# 3. Create a verified snapshot prior to upgrade
.venv/bin/python scripts/verify-upgrade-rollback.py snapshot \
  --region-root .cache/web_outputs/region_jobs \
  --generation-root .cache/generation_runs \
  --snapshot-dir .cache/snapshots/pre-v3.1.0 \
  --target-version 3.1.0

# 4. Atomically roll back from a verified snapshot
.venv/bin/python scripts/verify-upgrade-rollback.py restore \
  --snapshot-dir .cache/snapshots/pre-v3.1.0 \
  --region-root .cache/web_outputs/region_jobs \
  --generation-root .cache/generation_runs
```

## 3. Evidence Boundary

- **Implemented & unit/pipeline-tested**: Archive module/exclusion auditing, Docker
  dependency/context alignment, SQLite online backup + `.npy` artifact SHA-256
  verification, and atomic workspace rollback (`tests/test_release_packaging.py` and
  `tests/test-release-pipeline.sh`).
- **Pending external verification (`F15` remains `In Progress` / `partial`)**:
  Physical Android/tablet hardware checks, full M1/GPU memory budget profiling under
  live diffusion inference, and final visual polish signoff on merged `studio.html`.
