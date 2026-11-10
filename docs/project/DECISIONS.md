# Decision log

These are the working decisions inferred from the accepted project direction and
implemented contracts. They do not manufacture a model-quality or release approval.
Changes record their evidence and the scope they supersede.

| ID | Decision | Rationale | Consequence |
| --- | --- | --- | --- |
| ADR-001 | Preserve native precision and separate generative quality lanes | ARM64 usefulness and high-quality research are different constraints | No forced heavy diffusion stack on mobile |
| ADR-002 | Compose aligned base/candidate with confidence and explicit protection | Different surfaces need different reconstruction policy | Masks/editability first; base errors still need auditing |
| ADR-003 | Unknown regions stay conservative | Segmentation is uncertain and does not identify every zip/logo | No all-foreground-is-fabric fallback |
| ADR-004 | Manual brush before automatic masks | Real editable protection can be tested independently | Auto segmentation remains F09 with its own evidence |
| ADR-005 | Reuse existing CLI/studio and version persistence | Retain working behaviour and avoid a framework rewrite | API/storage changes need migration/compatibility checks |
| ADR-006 | Explicit local Comfy graph with durable run identity | Providers/model families differ; uncertain outcomes can duplicate runs | No guessed graph/weights or silent cross-provider failover |
| ADR-007 | No default synthetic grain/sharpening/face restoration | Finishing can conceal plasticity or change identity | Promote only from visual evidence |
| ADR-008 | GitHub specs/evidence plus Linear coordination | One versioned contract and one execution board | Notion is not a second tracker; Vercel is not the task system |
| ADR-009 | Keep current Studio local | Filesystem routes, workers and GPUs are not a reviewed public service | Public hosting requires a separate architecture/security decision |
| ADR-010 | Implementation evidence is distinct from release | Most current work is on an open branch | Status must name branch/SHA and remaining gates |

## Prior experiment decisions to retain

Nomos8kSC showed synthetic/checkerboard-like skin/fabric on some photographs and
is not the accepted final quality target. The previous source-fusion finish softened
useful VOSR detail and was rejected. Do not revive either from reputation alone.
The single-step/multi-step VOSR decision remains evidence-driven; do not continue
spending compute when the challenger fails to improve the accepted reference.

## New ADR template

- ID/title/date and status (proposed, accepted, superseded).
- Concrete problem, affected task/interfaces and known evidence.
- Options considered, including keeping the current design.
- Decision and why it improves the stated objective.
- Compatibility, data migration, cost/privacy/model-term impact.
- Validation, rollout/rollback and what would cause reconsideration.
- Owner/reviewer decision only when actually known; no fabricated approvals.

## Background queue and cancellation boundary · 2026-11-10

F07-A extends the existing ComfyUI run ledger with a separate, bounded local task
queue, one process owner and one worker. Startup pins trusted graph/address;
requests identify saved job revisions. Interrupted runs require explicit resume.
Local cancellation prevents application and abandons polling, while disclosing that
GPU work may continue. Global interrupt/clear is rejected because it can affect
unrelated prompts. Revision-checked JobStore commits remain authoritative; the
`applying` state is the point after which cancellation conflicts. This additive
queue preserves the synchronous CLI. Cross-database exactly-once apply recovery,
aggregate generated-cache quotas and live/device certification remain open.
See [queue contract](../ASYNC_GENERATION.md).

## Imported mask suggestion boundary · 2026-11-10

F09 first adds a model-independent probability/review interface rather than shipping
invented weights or declaring generic segmentation labels structural protection.
Source/model/transform declarations bind imported scores. One staged proposal uses
optional artifacts in the existing versioned JobStore: budgets, cleanup and atomic
revisions remain shared. Staging does not alter active masks; accept fills only
untouched fields, and edits after staging invalidate acceptance. Old manifest readers
can ignore optional metadata/artifact keys; no existing mask representation changes.
Actual automatic inference and fine boundary refinement require separate weight,
label/terms, registration, accuracy and resource evidence. See the
[suggestion contract](../MASK_SUGGESTIONS.md).
