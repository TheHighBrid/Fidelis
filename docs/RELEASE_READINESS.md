# Evidence-Backed Production Release Readiness (`F16` / `MEL-68`)

Per [QUALITY_GATES.md](project/QUALITY_GATES.md), merging code is not automatically a
production release (`E4_released`). Fidelis Studio's release readiness gate
(`fidelis/studio/release_readiness.py` and `scripts/audit-release-readiness.py`)
computes a deterministic release dossier (`fidelis.release_readiness.v1`) and fails
closed whenever any required quality, operational, packaging, defect, or owner-signoff
gate is incomplete.

## Gate Checks

The candidate's `live_worker_verified` operational declaration is supported by
the actual F05-A/F07 local ComfyUI MPS receipts: qualified preflight, successful
same-grid RealeSR inference, protected/unknown pixel equality, scoped cancellation
and restart recovery with the same prompt ID. The private F07 receipt SHA256 is
`c9000c1dc686c2f7a9b535af8ce38b78185d494493275303c973e1c9e048c6a4`.
This closes the worker-operation declaration only. F06 SDXL texture qualification,
representative image-quality acceptance, physical touch review and final signoff
remain open, and no readiness thresholds or requirements have changed.

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

The latest rebuilt candidate is main `7d97abdc518d5f91aa842572eb662adc9b90cc97`
(after PR #109 `F07`, PR #112 `F05-A`, and PR #113 `F12-A`).
Deterministic `v3.1.0` archives (`dist/fidelis-v3.1.0.tar.gz`,
`dist/fidelis-v3.1.0.zip`, and `dist/fidelis-offline-bundle-v3.1.0.tar.gz`) were
rebuilt and passed `scripts/verify-upgrade-rollback.py audit-archive` against
`7d97abdc`, with artifacts retained off-repo under
`release-evidence/7d97abdc/packages/`. Because `dist/` is gitignored and not
committed, running `audit-release-readiness.py` in a fresh git checkout reports
`packages.verified_count: 0` unless those archives are present under `dist/`.
Final creative and production approval remain pending.

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

- **Tracked release candidate manifest**: [`config/release-candidate-v1.json`](../config/release-candidate-v1.json) links the rebuilt `7d97abdc` `v3.1.0` release archives (`dist/fidelis-v3.1.0.tar.gz`, `dist/fidelis-v3.1.0.zip`, `dist/fidelis-offline-bundle-v3.1.0.tar.gz`), explicit scope summary, 6 architectural/operational known limits, `verify-upgrade-rollback.py` snapshot/restore commands against baseline `5315046`, and verified Apple M1 (8 GB) device budgets + upgrade/rollback receipts (`documentation_and_rollback.rollback_ready: true`).
- **Current repository level**: `E1_fixture_and_protocol_tested` (`ready_for_release: false`).
- **Remaining external gates for `E4_released`**: Live ComfyUI SDXL/Clarity-style GPU texture workflow qualification (`F05`/`F06`), 60-case licensed corpus & comparator runs (`F12-A`, `F12`), 30-case blind dual-reviewer held-out quality acceptance (`F13`), physical Android/iOS touch hardware review (`F08`), and explicit dual-owner creative/release signoff (`F16`).
