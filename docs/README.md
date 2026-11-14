# Fidelis documentation map

Start with the current status and branch reality, then read the chapter relevant to
your task. The documentation describes an engineering alpha, not a certified release.

| Chapter | Canonical document | Purpose |
| --- | --- | --- |
| 01 Product direction | [Vision](project/VISION.md) | Users, final experience, boundaries and success |
| 02 Strategy | [Plan blueprint](../PLAN_BLUEPRINT.md) | Priorities and milestone model |
| 03 Engineering design | [Architecture](project/ARCHITECTURE.md) | Current/target modules, contracts and data flow |
| 04 Delivery plan | [Roadmap](project/ROADMAP.md), [detailed plan](FIDELIS_STUDIO_PLAN.md) | F01-F17 dependencies and acceptance |
| 05 Start working | [Onboarding](../ONBOARDING.md), [AGENTS](../AGENTS.md) | Setup, directives and first contribution |
| 06 Progress | [Status](project/STATUS.md), [task ledger](FIDELIS_STUDIO_TASKS.md) | Verified snapshot versus open gates |
| 07 Quality | [Quality gates](project/QUALITY_GATES.md) | Benchmark, operational and release evidence |
| 08 Risk | [Risks](project/RISKS.md), [decisions](project/DECISIONS.md) | Known defects, assumptions and tradeoffs |
| 09 Collaboration | [Working model](project/COLLABORATION.md), [contributing](../CONTRIBUTING.md) | Ownership, parallel lanes and integration |
| 10 Handoff | [Handoff](project/HANDOFF.md), [checkpoint template](project/CHECKPOINT_TEMPLATE.md) | Resume without conversation history |

Operational references:

- [Regional workspace and brush editing](REGIONAL_WORKSPACE.md)
- [Native pixel inspection](NATIVE_INSPECTION.md)
- [Same-host Chromium browser acceptance](BROWSER_ACCEPTANCE.md)
- [Imported mask suggestions](MASK_SUGGESTIONS.md)
- [Explicit structural ROIs and crop checks](STRUCTURAL_ROIS.md)
- [Internal ROI drift screening and protection](ROI_DRIFT_SCREENING.md)
- [ComfyUI texture adapter](COMFY_TEXTURE_BACKEND.md)
- [Live worker preflight and VRAM budget](WORKER_PREFLIGHT.md)
- [Background generation and recovery](ASYNC_GENERATION.md)
- [Aligned-pass reblend CLI](REGION_REBLEND.md)
- [Saved master export and batch recovery](STUDIO_EXPORT.md)
- [Color-managed 16-bit and provenance export](MANAGED_EXPORT.md)
- [Resumable batch processing and rate limits](BATCH_PROCESSING.md)
- [Explicit benchmark corpus and freeze](BENCHMARK_CORPUS.md)
- [Comparator runner adapters and cost normalization](COMPARATOR_RUNNERS.md)
- [Held-out quality acceptance and inter-rater reliability](QUALITY_ACCEPTANCE.md)
- [Photo model candidates](PHOTO_MODEL_CANDIDATES.md)
- [Apple M1 (8 GB) precision-base hardware audition](APPLE_M1_PRECISION_BASE_AUDITION.md)
- [Studio packaging, upgrade and rollback verification](RELEASE_PACKAGING.md)
- [Release readiness dossier and signoff audit](RELEASE_READINESS.md)
- [Legacy native guide](LEGACY_RUNTIME_GUIDE.md)
- [VOSR experiment](../experiments/VOSR_FIDELITY_SWEEP.md)
- [Machine-readable backlog snapshot](project/backlog.json)
- [Integration map](project/INTEGRATIONS.md)

Do not copy the roadmap into another system and treat both copies as independently
live. Update GitHub specs and Linear coordination using the integration policy.
