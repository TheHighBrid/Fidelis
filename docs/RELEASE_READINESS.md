# Evidence-Backed Production Release Readiness (`F16` / `MEL-68`)

Per [QUALITY_GATES.md](project/QUALITY_GATES.md), merging code is not automatically a
production release (`E4_released`). Fidelis Studio's release readiness gate
(`fidelis/studio/release_readiness.py` and `scripts/audit-release-readiness.py`)
computes a deterministic release dossier (`fidelis.release_readiness.v1`) and fails
closed whenever any required quality, operational, packaging, defect, or owner-signoff
gate is incomplete.

## Gate Checks

1. **Core Deliverables (`F01..F15`)**: Every core milestone deliverable in
   `docs/project/backlog.json` must reach a closed state (`Done`, `Completed`, or
   `Released`).
2. **Blocking Defects (`D01..D04`)**: All Priority-2 audit defects must be merged and
   closed on `main` (not merely `In Review` on an open PR).
3. **Release SHA & `main` Merge**: Requires a valid 7..40 hex Git commit SHA and
   `merged_to_main: true`.
4. **Verified Release Packages**: Linked release archives must carry 64-hex SHA-256
   digests verified against on-disk bytes when present.
5. **Held-Out Quality & Operational Gates**: Requires `quality_gate.overall_status == "accepted"`
   with a recorded `report_sha256`, plus verified live worker preflight, target-device
   resource budget measurements, and workspace upgrade/rollback protection.
6. **Scope, Known Limits & Rollback Plan**: Requires explicit scope summary, non-empty
   known limits list, and snapshot/restore rollback commands referencing the previous
   stable SHA/tag.
7. **Owner Creative & Release Signoff**: Requires `owner_release_signoff.status == "approved"`
   with named `creative_owner`, `release_owner`, and `signed_at` timestamp.

## CLI Usage

```bash
# Audit current repository release readiness (exits 2 while gates remain open)
.venv/bin/python scripts/audit-release-readiness.py \
  --output .cache/release-readiness-dossier.json

# Emit the readiness dossier for CI/reporting without failing the command
.venv/bin/python scripts/audit-release-readiness.py --allow-blocked
```

## Current Evidence Status

- **Tracked release candidate manifest**: [`config/release-candidate-v1.json`](../config/release-candidate-v1.json) links the verified `v3.1.0` release archives (`dist/fidelis-v3.1.0.tar.gz`, `dist/fidelis-v3.1.0.zip`, `dist/fidelis-offline-bundle-v3.1.0.tar.gz`), explicit scope summary, 6 architectural/operational known limits, `verify-upgrade-rollback.py` snapshot/restore commands against baseline `5315046`, and verified Apple M1 (8 GB) device budgets + upgrade/rollback receipts (`packages.verified_count: 3`, `documentation_and_rollback.rollback_ready: true`).
- **Current repository level**: `E1_fixture_and_protocol_tested` (`ready_for_release: false`).
- **Remaining external gates for `E4_released`**: Merge PR #12 to `main` (`merged_to_main: true`, closing `D01..D04` on `main`), run live ComfyUI GPU texture worker qualification (`F05-A`, `F06`, `F07`), complete 60-case licensed corpus & 30-case blind held-out quality acceptance (`F12-A`, `F12`, `F13`), complete physical Android/iOS touch hardware review (`F08-B`, `F15`), and record owner creative/release signoff.
