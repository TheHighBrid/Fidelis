# Project integration and ownership map

## Active project

- Linear: https://linear.app/melato/project/fidelis-studio-a057f366fa71
- Linear project identifier: `P-MEL-3`.
- GitHub: https://github.com/TheHighBrid/Fidelis
- Observed umbrella: GitHub issue #11 attached to Linear `MEL-53`.
- Current implementation PR: https://github.com/TheHighBrid/Fidelis/pull/12

The project contains six milestones, 27 scoped child work items and the reused
umbrella. F01-F17, six bounded work units and four audit defects retain stable
plan IDs. Actual per-item IDs and URLs are in [backlog.json](backlog.json).
No contributor, due date, invitation or permission change was invented.

## System responsibilities

| Platform | Role in this setup | State |
| --- | --- | --- |
| GitHub | Versioned source, specs, architecture, directives, decisions and evidence | Canonical repository documents |
| Linear | Task priority/ownership/status, parent work and blocking dependencies, milestones | Project created in connected Melato workspace |
| Notion | Optional future reader/writing surface if needed | Searched; no Fidelis hub found; no duplicate tracker/database created |
| Vercel | Optional future reviewed docs/front-end hosting | Searched; no Fidelis project found; no deployment created |

Linear was selected because this is engineering coordination with bounded work,
dependencies and multiple contributors. Adding parallel Notion tasks would create
an unnecessary second board. Hosting the current local-filesystem/GPU service on
Vercel is not part of documentation setup and requires a separate product decision.

## Synchronization policy

GitHub specifications govern product/contract truth. Linear governs live
coordination. A checkpoint refreshes the committed task/status snapshot with actual
issue links. The existing umbrella attachment was observed; no broad automatic
bidirectional document or issue sync was configured or claimed.

When changing task scope: update its existing F-ID issue and the affected spec.
When completing code: attach the PR/SHA/tests and update review/merge state.
When releasing: record separate quality/device/package evidence and owner signoff.
Never close a live quality gate merely to match a board's automatic progress bar.

## Reusing this setup

Search the same project and F-ID before creating a record. Reuse existing IDs from
the backlog; do not rerun the import and create duplicates. Assign people only when
real responsibility is agreed. Do not invite collaborators, send messages or alter
sharing as an incidental consequence of project organization.
