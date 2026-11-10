# Roadmap, milestones and progress checkpoints

The task contract is [FIDELIS_STUDIO_PLAN.md](../FIDELIS_STUDIO_PLAN.md); current
coordination is [Linear](https://linear.app/melato/project/fidelis-studio-a057f366fa71).
The committed [backlog](backlog.json) contains actual IDs, links, scope and acceptance.
Dates and staffing are not agreed. The earlier solo effort range is a planning
hypothesis, not a deadline or a substitute for resource/quality evidence.

## Milestone chapters

| Milestone | Scope | Current snapshot | Exit evidence |
| --- | --- | --- | --- |
| M0 Foundations | F01-F03 | Implemented in open PR; In Review | Plan, tested region compositor and file CLI. Review/merge location is explicit. |
| M1 Runnable two-pass alpha | F04-F07 | Partial; live worker/async gates open | Actual selected base and compatible live texture output, persistent artifacts, scoped restart/cancel and no duplicate submission. |
| M2 Protected regional studio | F08-F11 | Editor partial; masks/export gates ahead | Device-accepted editor, confidence-gated auto masks, critical structure protection, deliberate colour/alpha/precision exports. |
| M3 Measured quality beta | F12-F13 | Not accepted; preparation can proceed | Frozen rights-cleared corpus and held-out comparator report with agreed criteria, defects and uncertainty. |
| M4 Daily production release | F14-F16 | Not released | Resumable bounded batches, measured target-device resources, packaging/rollback and final creative/release signoff. |
| M5 Optional challenger expansion | F17 | Deferred | Independent compatible graph/terms and measured quality/cost win after core release. |

F01-F04 are In Review in Linear because the implementation is on an open PR. This
does not erase the achieved code/tests, and does not call that work released.
No task-count percentage is used as a quality or product completion score.

## Stable task map

| Task | Milestone | Implementation | Coordination | Depends on |
| --- | --- | --- | --- | --- |
| [F01 / MEL-54](https://linear.app/melato/issue/MEL-54/f01-establish-product-plan-and-audit-baseline) · Establish product plan and audit baseline | M0 | implemented | In Review | none |
| [F02 / MEL-56](https://linear.app/melato/issue/MEL-56/f02-deliver-protected-linear-light-region-composition) · Deliver protected linear-light region composition | M0 | implemented | In Review | F01 |
| [F03 / MEL-55](https://linear.app/melato/issue/MEL-55/f03-deliver-aligned-pass-cli-and-reproducibility-recipe) · Deliver aligned-pass CLI and reproducibility recipe | M0 | implemented | In Review | F02 |
| [F04 / MEL-57](https://linear.app/melato/issue/MEL-57/f04-persist-versioned-artifacts-with-storage-budgets) · Persist versioned artifacts with storage budgets | M1 | implemented | In Review | F03 |
| [F05 / MEL-58](https://linear.app/melato/issue/MEL-58/f05-qualify-installed-runtimes-and-select-a-precision-base) · Qualify installed runtimes and select a precision base | M1 | partial | In Progress | F04 |
| [F06 / MEL-60](https://linear.app/melato/issue/MEL-60/f06-qualify-one-live-compatible-texture-workflow) · Qualify one live compatible texture workflow | M1 | partial | In Progress | F05 |
| [F07 / MEL-61](https://linear.app/melato/issue/MEL-61/f07-implement-durable-async-jobs-and-scoped-cancellation) · Implement durable async jobs and scoped cancellation | M1 | partial | In Progress | F06 |
| [F08 / MEL-59](https://linear.app/melato/issue/MEL-59/f08-accept-editable-regional-review-and-native-pixel-inspection) · Accept editable regional review and native-pixel inspection | M2 | partial | In Progress | F03, F04 |
| [F09 / MEL-62](https://linear.app/melato/issue/MEL-62/f09-qualify-confidence-gated-automatic-segmentation) · Qualify confidence-gated automatic segmentation | M2 | not_started | Backlog | F05, F08 |
| [F10 / MEL-64](https://linear.app/melato/issue/MEL-64/f10-protect-structural-rois-and-screen-internal-drift) · Protect structural ROIs and screen internal drift | M2 | not_started | Backlog | F06, F09 |
| [F11 / MEL-65](https://linear.app/melato/issue/MEL-65/f11-implement-colour-managed-alpha-and-high-precision-exports) · Implement colour-managed alpha and high-precision exports | M2 | not_started | Backlog | F10 |
| [F12 / MEL-63](https://linear.app/melato/issue/MEL-63/f12-freeze-rights-cleared-corpus-and-comparator-runners) · Freeze rights-cleared corpus and comparator runners | M3 | not_started | Backlog | F05 |
| [F13 / MEL-66](https://linear.app/melato/issue/MEL-66/f13-calibrate-and-pass-held-out-quality-acceptance) · Calibrate and pass held-out quality acceptance | M3 | not_started | Backlog | F06, F07, F08, F09, F10, F11, F12 |
| [F14 / MEL-67](https://linear.app/melato/issue/MEL-67/f14-deliver-resumable-bounded-batch-processing) · Deliver resumable bounded batch processing | M4 | not_started | Backlog | F07, F11 |
| [F15 / MEL-69](https://linear.app/melato/issue/MEL-69/f15-polish-responsive-studio-and-verify-packaging) · Polish responsive studio and verify packaging | M4 | not_started | Backlog | F08, F14 |
| [F16 / MEL-68](https://linear.app/melato/issue/MEL-68/f16-publish-evidence-backed-production-release) · Publish evidence-backed production release | M4 | not_started | Backlog | F13, F15 |
| [F17 / MEL-70](https://linear.app/melato/issue/MEL-70/f17-evaluate-optional-challenger-adapters-after-core-release) · Evaluate optional challenger adapters after core release | M5 | deferred | Backlog | F16 |

F13 additionally depends on D04; F16 additionally depends on D01-D03. These audit
blockers are represented as native Linear blocking relations rather than buried
notes. Prerequisites can block final acceptance while independent preparatory
subtasks remain available.

## Bounded next work units

| Work unit | Suggested responsibility | Readiness / boundary |
| --- | --- | --- |
| [F05-A / MEL-76](https://linear.app/melato/issue/MEL-76/f05-a-prepare-a-reproducible-live-worker-preflight) · Prepare a reproducible live-worker preflight | Runtime / infrastructure | Blocked by unavailable worker/access, not by missing fixture code. |
| [F05-B / MEL-75](https://linear.app/melato/issue/MEL-75/f05-b-record-candidate-model-hashes-and-usage-terms) · Record candidate model hashes and usage terms | Model research | Can prepare the manifest/review before live inference. |
| [F07-A / MEL-77](https://linear.app/melato/issue/MEL-77/f07-a-build-bounded-async-execution-and-ownership-safe-cancellation) · Build bounded async execution and ownership-safe cancellation | Job orchestration | Fixture-driven implementation can proceed independently of the GPU quality gate. |
| [F08-A / MEL-78](https://linear.app/melato/issue/MEL-78/f08-a-add-actual-native-image-pixel-crop-inspection) · Add actual native image-pixel crop inspection | Studio UX | No GPU required; current zoom is explicitly preview-only. |
| [F08-B / MEL-80](https://linear.app/melato/issue/MEL-80/f08-b-complete-same-host-browser-and-target-device-acceptance) · Complete same-host browser and target-device acceptance | QA / UX | Previous browser-to-executor connection was refused; use a materially different reachable test setup. |
| [F12-A / MEL-79](https://linear.app/melato/issue/MEL-79/f12-a-prepare-corpus-rights-and-roi-manifest) · Prepare corpus rights and ROI manifest | Evaluation | Schema/inventory preparation is independent of live model outputs. |

## Checkpoint protocol

At every task handoff: record scope, actual owner, branch/base/result SHA, changed
contracts, commands/results, artifact links, evidence level, open defects and next
action. Use [the template](CHECKPOINT_TEMPLATE.md). At each milestone, verify every
exit and blocker rather than inferring acceptance from elapsed time or test count.

M1 cannot close on the Comfy fixture. M2 cannot close on preview zoom alone. M3
cannot close on synthetic crops or unavailable competitor outputs. M4 cannot close
merely because the application has a version number or a container file.
