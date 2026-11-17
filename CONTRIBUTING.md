# Contribution and review workflow

Read [AGENTS.md](AGENTS.md) and [Onboarding](ONBOARDING.md) before contributing.
The same engineering/evidence rules apply to people and AI agents.

## Task lifecycle

| State | Meaning |
| --- | --- |
| Backlog | Scoped, but not yet selected or still dependency-bound |
| Todo | Ready bounded work, with acceptance and required inputs |
| In Progress | Implementation/acceptance work is underway or partly implemented |
| In Review | Implementation evidence exists and a PR awaits review/merge |
| Done | The issue's acceptance is met and its delivery location is recorded |

An implementation can be complete on a branch while the issue is In Review.
Merged is not released; tested is not quality accepted. When an issue is blocked,
state the missing capability and blocker relationship, not just a status label.
Use native team statuses rather than inventing a new workspace workflow.

## Claim and implement

1. Reuse the existing F-ID or defect issue; check for a duplicate first.
2. Claim an owner and record scope, base SHA, dependencies and touched interfaces.
3. Work in an isolated branch/worktree. Coordinate overlapping file ownership.
4. Keep contracts stable or document a migration before changing persisted data.
5. Add meaningful tests for changed behaviour and retain known failure evidence.
6. Update documentation and affected task status; do not invent a completion rate.

Parallel lanes and allowed overlaps are in [Collaboration](docs/project/COLLABORATION.md).
No collaborator is assigned merely because their account exists in the workspace.

## Pull requests

Use the PR template. Explain the concrete problem/result, validation and limits.
Link the Linear issue and relevant GitHub reference; include the task ID in the
branch, for example `work/F07-async-job-cancel`. Do not mix a model experiment,
a storage migration and a visual redesign into one unreviewable change.

Reviewers check exact protection, dimensions/registration, failure handling,
resources, model/recipe provenance, privacy, compatibility and quality claims.
A reviewer must know which evidence is fixture, live or visually accepted.
Resolve critical defects before promoting a quality/release milestone.

The contributor updates the issue and handoff after merge. The person integrating
work confirms the current base, runs relevant combined checks and records any
remaining device/quality gate. Integration does not authorize publishing a public
service or running paid inference outside the selected execution policy.

## Decisions and documentation

Use the [decision log](docs/project/DECISIONS.md). Add an ADR for changes to model
families, inference providers, colour/alpha contract, job storage schema, public
hosting or architecture. Routine bug fixes need a precise issue and tests, not a
ceremonial ADR. Update the same documents instead of starting competing plans.

GitHub specifications and the committed backlog snapshot are versioned records.
Linear is the coordination board; refresh the snapshot at a checkpoint. There is
no claim of bidirectional automatic sync. The existing GH #11 / MEL-53 connection
is an observed umbrella link, not proof that every new task is mirrored.

## Completion receipt

Record: issue, branch/SHA, behaviour delivered, tests with commands/results,
artifact locations, remaining gate/defect, next action and review/merge state.
Use [the checkpoint template](docs/project/CHECKPOINT_TEMPLATE.md).
No secrets, private source images or credential values belong in a receipt.
