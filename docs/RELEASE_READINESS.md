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
   digests verified against on-disk bytes. Missing archives fail the release gate.
5. **Held-Out Quality & Operational Gates**: Requires `quality_gate.overall_status == "accepted"`
   with a recorded `report_sha256`, plus verified live worker preflight, target-device
   resource budget measurements, and workspace upgrade/rollback protection.
6. **Scope, Known Limits & Rollback Plan**: Requires explicit scope summary, non-empty
   known limits list, and snapshot/restore rollback commands referencing the previous
   stable SHA/tag.
7. **Owner Creative & Release Signoff**: Requires `owner_release_signoff.status == "approved"`
   with named `creative_owner`, `release_owner`, and `signed_at` timestamp.

Both roles may be held by the same owner: the current policy and validators require
named roles but do not require distinct people. Execution authorization does not
approve either final signoff. F13's independent blind reviewers remain a separate
requirement and are not replaced by this role interpretation.

## Candidate reconciliation, 2026-11-24

The candidate is main `d6f420ccf1754c79931c9822ec5127b98ab0df5c`.
The prior manifest commit `24a2eb7` is an ancestor of main (verified with
`git merge-base --is-ancestor`). `merged_to_main` is therefore true. Historical
archive digests remain identified as historical; current candidate archives need
fresh build and byte verification. The current local audit finds zero package
files, so packaging remains open. Final creative and production approval remain
pending under the owner's explicit instruction.

All 97 Melato assets already have the approval recorded in
[CORPUS_ACQUISITION_PROPOSAL.md](CORPUS_ACQUISITION_PROPOSAL.md). Missing local
bytes are a recovery task, not a request to repeat that rights approval. Fixed
corpus categories, splits, ROI requirements and human-review gates remain intact.

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
