# Checkpoint · Unified Studio & Follow-Up PR Reconciliation (`2026-11-19`)

- **Date**: 2026-11-19 (verified `2026-11-20T03:56Z`)
- **Branch**: `work/unified-studio-20261119` (cleanly stacked onto `PR #64` `cursor/integrate-pr12-pr14-7a85` @ `b031001`)
- **Evidence level**:
  - `E1_fixture_and_protocol_tested` across all unified PRs and regressions
  - `E2` zero-cost live inference on Apple M1 (`Darwin arm64`, 8 GB unified memory) via `scripts/qualify-realesr-general-v3.py --record-live` (`RealeSR-general-v3`, BSD-3-Clause, `api_fee: 0`, `cloud_fallback: false`)
  - Same-host Headless Google Chrome (`157.0.8103.79`) CDP desktop (`1440×900`) and mobile touch (`390×844`) acceptance (`observed_defects: []`)

## 1. Reconciled Pull Requests & Branches

All concurrent engineering PRs on `TheHighBrid/Fidelis` were merged additively without discarding contributor APIs or working trees:

| PR | Scope / Linear | Reconciliation Summary |
| :--- | :--- | :--- |
| **#64** | Consolidated PR #12 + PR #14 on `main` (`1c954cd` .. `b031001`) | Integration base |
| **#76** | `MEL-64` / `F10` structural drift screening refactor & complexity cleanup | Clean merge |
| **#77** | `MEL-71` / `D03` legacy browser HTML escaping, cache symlink escape, CRLF fix | Clean merge |
| **#79** | `MEL-75` / `F05-B` provenance & `capabilities.py` path containment | Clean merge |
| **#80** | `MEL-76` / `F05-A` worker preflight policy bounds + E721 type-check cleanup | Clean merge + lint fix |
| **#66** | Studio Krea UI polish (`review-ui.js`, docked native inspection, narrow stacking) | Clean merge |
| **#67** | `MEL-77` queue cancellation registry, ledger recovery & shutdown hardening | Clean merge |
| **#78** | `MEL-72` fresh nonempty artifact receipt for tiled and direct upscale | Clean merge |
| **#81** | Fail closed when protected-export verification has zero locked pixels | Clean merge |
| **#73** | `MEL-62` / `F09` confidence routing & spatial/export lock consistency (#69..#73) | Clean merge |
| **#48** | `MEL-74` `fidelis/eval/metric_contract.py` + `tests/test_metric_contract.py` | Additive merge preserving `metric_context` JSON schema in `scripts/upscale.py` |
| **#65** | `F06` zero-cost `RealeSR-general-v3` texture workflow qualification (`M1/Android`) | Merged keeping hardened `test_web_uploads.py` |
| **#75** | `Bot 05` + `MEL-79` photographic protocol & Melato 97-asset off-repo inventory (#61 + #75) | Additive merge: preserved `corpus_manifest.py` lock APIs and added `melato_corpus_manifest.py` + `test_melato_corpus_manifest.py` |
| *Local E2E fix* | `tests/e2e/test_tier4_scenarios.py` | Updated held-out scenario comparator list to `("pinned_clarity", "dated_krea")` |

## 2. Release Packaging & CI Coverage

- Updated `REQUIRED_ARCHIVE_PATHS` in `fidelis/studio/packaging.py` to require all newly integrated modules and CLI scripts (`confidence_routing.py`, `metric_contract.py`, `melato_corpus_manifest.py`, `photographic_protocol.py`, `texture_eval_hooks.py`, `qualify-realesr-general-v3.py`, `qualify_realesr_*.py`, `run-photographic-protocol.py`, `validate-corpus-manifest.py`, `generate-photographic-protocol-fixtures.py`).
- Updated `.github/workflows/ci.yml` to run all added test modules explicitly (`test_melato_corpus_manifest.py`, `test_metric_contract.py`, `test_f06_realesr_qualification.py`, `test_cancellation_registry.py`, `test_confidence*.py`, `test_f09_confidence_boundary_contract.py`, `tests/review-ui.cjs`, `test_browser_evidence.py`, `test_browser_acceptance_report.mjs`).
- Rebuilt deterministic `v3.1.0` release & offline archives (`scripts/package-release.sh 3.1.0`, `scripts/package-offline-bundle.sh 3.1.0`) and refreshed `config/release-candidate-v1.json`.

## 3. Remaining External Gates (`E2..E4`)

- **Live GPU ComfyUI SDXL workflow (`F05-A` / `F06` / `F07`)**: `scripts/worker-preflight.py --require-qualified` against a reachable ComfyUI GPU endpoint remains external.
- **Photographic corpus masters & dual-reviewer human signoff (`F12-A` / `F12` / `F13`)**: 30/60 corpus slots remain missing (30 off-repo Melato slots await local `--master-root` verification + commercial license clearance for non-GT slots, and 30 blind held-out ballots require 2 human reviewers).
- **Physical touch hardware & release signoff (`F08-B` / `F15` / `F16`)**: Physical Android/iOS touch/stylus QA, `main` PR merge, and owner release signoff remain open.
