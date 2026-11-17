# Collaboration and parallel execution

## Source-of-truth map

| Record | Owner/system | Update rule |
| --- | --- | --- |
| Product contract, architecture, directives, code, tests | GitHub | Versioned PR/commit |
| Task assignment, priority, dependencies, coordination status | Linear Fidelis project | Update the existing F-ID issue |
| Committed task/status evidence | GitHub snapshot | Refresh at a verified checkpoint |
| Decisions | GitHub decision log/ADRs | Link the task and evidence |
| Creative/release judgment | Repository owner | Record after concrete review, never infer |

GH #11 is observed as attached to Linear MEL-53. Reuse it as the umbrella. Do not
assume every issue/document is automatically mirrored or claim synchronization
that was not configured and checked. External task links are in `backlog.json`.
No invites, permission changes or fabricated contributor assignments are made.

## Safe parallel lanes

| Lane | Typical tasks | Shared boundary | Coordination rule |
| --- | --- | --- | --- |
| Runtime/model research | F05/F06, weight/graph evidence | Candidate artifact + recipe | No compositor/UI edits without agreement |
| Job orchestration | F07/F14 | Revisioned job/backend contracts | One owner for state/schema migrations |
| Studio UX | F08/F15 | Mask/edit API and preview contracts | Agree API changes before implementation |
| Masks/structure | F09/F10 | Float masks, confidence and protection | No automatic unlock of explicit masks |
| Colour/export | F11 | Working/export colour contract | Reapply exact-lock invariant after finishing |
| Benchmark/evidence | F12/F13 | Frozen corpus, recipes and defect schema | Separate calibration from held-out review |
| Documentation/release | F01/F16 | Verified status and accepted scope | Never promote partial gates from prose |

A contributor claims one issue, names files/interfaces, and uses an isolated
branch/worktree. Shared `store.py`, `http.py`, `pipeline.py`, presets and manifests
need one integrating owner or agreed file-level ownership. Avoid simultaneous
uncoordinated edits to the same state machine. No extra agent invocation is implied
by this operating model; follow the user's delegation instructions.

## Ready independent work

- Prepare the rights/hash/ROI schema and corpus inventory without running a GPU.
- Design/test scoped async cancellation and job ownership against protocol fixtures.
- Reconcile legacy provenance/metric claims and the verified pipeline import defect.
- Complete browser/device acceptance once a reachable preview/device path exists.
- Record actual weight/runtime evidence when a worker becomes available.

The model-quality gate remains blocked until actual compatible inference can run.
Do not mark an entire task ready just because one independent subtask is ready.

## Checkpoints

Every task handoff uses the checkpoint template. At each milestone, the integrating
contributor reviews all exits, open defects and resource/quality evidence. A weekly
review is a suggested cadence, not a scheduled meeting. No meetings, dates or
attendees have been created. Update status when evidence changes, not merely on
elapsed time.

## Platform choice

Linear was selected for issues, dependency links, milestones and ownership in the
connected Melato workspace. Notion was searched for an existing Fidelis hub and
none was found; creating a duplicate documentation/task database was unnecessary.
Vercel was checked for an existing Fidelis project and none was found. Hosting is
separate from this coordination task; no deployment or public service was created.
