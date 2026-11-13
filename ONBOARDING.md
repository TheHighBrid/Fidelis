# Contributor onboarding

## First 20 minutes

1. Read `README.md`, `AGENTS.md`, `docs/project/STATUS.md` and `docs/project/RISKS.md`.
2. Confirm your branch and base SHA. Studio work currently lives in PR #12 on
   `feat/region-aware-studio`; `main` documentation does not imply that code merged.
3. Open the [Linear project](https://linear.app/melato/project/fidelis-studio-a057f366fa71),
   inspect dependencies, and claim one bounded issue. Read its acceptance criteria.
4. Read the relevant architecture/contract and existing tests before changing it.
5. Record the files/interfaces you will own and your first verification command.

The compact [handoff](docs/project/HANDOFF.md) is intended for a fresh AI context.
Do not ask the owner to restate decisions already captured in these documents.

## Checkout and isolation

```bash
git clone https://github.com/TheHighBrid/Fidelis.git
cd Fidelis
git fetch origin
git switch feat/region-aware-studio
git switch -c work/Fxx-short-scope
```

Use a separate checkout/worktree for each simultaneous contributor. Do not run a
reset/clean on a shared working directory. Confirm `git status` before editing.
When PR #12 merges, branch from the accepted `main` instead and update this guide.

## Python environment

The current CI uses Python 3.11; the audited development snapshot used 3.12.
Use a compatible interpreter and create `.venv` once if it does not exist. Example
for a machine with Python 3.12 installed:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install pillow numpy scipy scikit-image opencv-python-headless pyyaml
.venv/bin/python -m pip install -r requirements-studio.txt
```

The first command bootstraps the environment. After that, use `.venv/bin/python`,
not a system interpreter. The dependency list above mirrors the development test
lane; it is not a locked production image. Historical `requirements.txt` is retained
for the existing runtime. Dependency/runtime pinning and packaging are release work.
Do not install PyTorch, model weights or GPU drivers just to run fixture tests.

Node is used for editor syntax and browser/native brush math parity. Confirm an
available Node runtime; the existing GitHub runners provide one. Do not silently
count a skipped Node parity test as a device/browser acceptance result.

## Run the application and tests

```bash
.venv/bin/python scripts/web-ui.py --bind 127.0.0.1 --port 8765
```

Open `http://127.0.0.1:8765/regions`. Supply aligned, untagged sRGB RGB PNG base and
texture passes. NPZ masks are optional; paint regions directly. Unknown regions
stay unchanged. Saving bakes masks and resets unsaved undo history.

```bash
.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v
PATH="$PWD/.venv/bin:$PATH" bash tests/test-web-ui.sh
PATH="$PWD/.venv/bin:$PATH" bash tests/smoke-test.sh
node --check fidelis/studio/editor.js
git diff --check
```

Use the relevant additional shell suites listed in `.github/workflows/ci.yml` for
native model registration, audition, release or VOSR changes. Do not claim all CI
checks passed from the three commands above. The recorded 62 local tests are a
snapshot; rerun relevant tests for your actual change and record exact results.

## Capabilities and local inference

```bash
.venv/bin/python scripts/backend-doctor.py
```

This reads actual availability/checksums and probes ComfyUI; it does not download
weights or submit a generation. The current executor's missing worker is recorded
in [Status](docs/project/STATUS.md), not assumed to describe your computer.
A compatible local worker, exported graph, actual weights and their provenance are
required for live texture work. See [the adapter contract](docs/COMFY_TEXTURE_BACKEND.md).
Protocol fixtures use fixed test pixels and cannot certify enhancement quality.

For native device setup, use [the retained runtime guide](docs/LEGACY_RUNTIME_GUIDE.md)
and [candidate notes](docs/PHOTO_MODEL_CANDIDATES.md), checking current terms and
actual device support before installation. There is no universal GPU guarantee.

## Files, data and access

- `.cache/web_outputs/region_jobs`: local persistent regional jobs and artifact data.
- `.cache/generation_runs`: local generation ledger and cached texture outputs.
- Models, keys and user images stay outside version control.
- Use licensed/consented images for quality evidence; never upload source images
  merely because a local worker is unavailable.
- Do not expose the current local HTTP service publicly. Existing legacy routes
  are not an authenticated cloud service. Do not assume the Dockerfile means it is.

## Your first contribution

Choose a ready work unit from the parallel lanes. Use its issue ID in the branch
and PR; include scope, before/after behaviour, tests and remaining acceptance.
Update the related docs, evidence and Linear issue. Stop only at a concrete gate
that requires unavailable access or owner judgment; finish independent work first.

## Optional background generation

Enable a trusted local graph explicitly using `--texture-workflow`. Read the
[background queue guide](docs/ASYNC_GENERATION.md) before using its cancel/resume
controls; local cancellation does not interrupt submitted GPU work.

## Master export

See [Master exports](docs/STUDIO_EXPORT.md) for ICC, 16-bit and alpha reblending
through the CLI and resumable export of saved Studio jobs.
