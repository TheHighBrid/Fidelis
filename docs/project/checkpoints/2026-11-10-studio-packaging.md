# Studio Packaging & Upgrade/Rollback Protection Checkpoint · 2026-11-10

- **Issue / Task**: `F15` (`MEL-69` — Polish responsive studio and verify packaging)
- **Branch**: `work/mel-69-studio-packaging-upgrade` (based on `origin/feat/region-aware-studio` `f84287993c9bc213dc47859b297a5a275381101d`)
- **State**: `In Progress` (`implementation: "partial"`)

## Summary of Changes

1. **Release Archive & Container Packaging Hardening (`scripts/package-release.sh`, `scripts/package-offline-bundle.sh`, `Dockerfile`, `.dockerignore`)**:
   - Excluded `.cache`, `.fidelis`, `runtime`, `models`, `.env*`, and audition/corpus output directories from release tarballs, zip archives, offline bundles, and Docker build contexts so local workspaces and secrets cannot leak into artifacts.
   - Updated `Dockerfile` to install `requirements-studio.txt` (`httpx==0.28.1`) alongside `requirements.txt`.
2. **Archive Auditor & Workspace Upgrade/Rollback Guard (`fidelis/studio/packaging.py`, `scripts/verify-upgrade-rollback.py`)**:
   - Added `audit_release_archive` to verify `REQUIRED_ARCHIVE_PATHS` (`fidelis/studio`, `fidelis/postprocess`, `fidelis/eval`, `config/benchmark`, `requirements-studio.txt`, `.dockerignore`) and reject forbidden `.cache/`, `.venv/`, or `.env*` entries.
   - Added `verify_workspace_integrity`, `create_workspace_snapshot`, and `restore_workspace_snapshot` using SQLite online backup (`sqlite3.Connection.backup`), `.npy` SHA-256 digest verification, and atomic directory replacement so saved regional jobs and generation runs survive upgrades and rollbacks without data loss.
3. **Tests & CI (`tests/test_release_packaging.py`, `tests/test-release-pipeline.sh`, `.github/workflows/ci.yml`)**:
   - Added 4 unit tests covering archive leak/missing-module detection, clean offline bundle auditing, workspace snapshot/upgrade/rollback round-trip, and corrupted `.npy` artifact detection + CLI recovery.
   - Wired `scripts/verify-upgrade-rollback.py audit-archive` into `tests/test-release-pipeline.sh`.

## Verification Results

- `.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v`: **129 tests passed** (125 baseline + 4 new `test_release_packaging.py` tests).
- `PATH="$PWD/.venv/bin:$PATH" bash tests/test-release-pipeline.sh`: passed.
- `PATH="$PWD/.venv/bin:$PATH" bash tests/test-web-ui.sh`: passed.
- `PATH="$PWD/.venv/bin:$PATH" bash tests/smoke-test.sh`: passed.
- `git diff --check`: clean.

## Remaining Gate for Full `F15` Completion

- Physical Android/tablet device checks, live M1/GPU memory budget measurements, and UI keyboard-focus/scroll polish on `studio.html` remain open; `F15` stays `In Progress` (`partial`).
