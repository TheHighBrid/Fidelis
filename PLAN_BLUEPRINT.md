# Fidelis plan blueprint

Version 1.0 · 2026-11-10 · Working product/engineering baseline.

## 1. Vision

A focused restoration studio for real creative production: natural skin and hair,
credible textiles and crisp product construction, with editable control over where
reconstruction is permitted. The intended benchmark combines Clarity-style
controlled generation and the requested Krea-style region workflow. Fidelity and
publishability outrank artificial sharpness.

Read [Vision and final product](docs/project/VISION.md) for user journeys and the
release contract. Read the [detailed implementation plan](docs/FIDELIS_STUDIO_PLAN.md)
for task scope, model assumptions and proposed quality thresholds.

## 2. Strategy

1. Retain the native ARM64 precision lane and the VOSR quality-reference history.
2. Build the application contracts independently of model reputation: aligned
   artifacts, exact protection, confidence routing, persistent revisions and honest evidence.
3. Qualify one compatible texture workflow on actual hardware before adding more.
4. Add automatic masks as suggestions over an editable manual foundation; uncertainty
   must reduce generated contribution rather than guess a material class.
5. Freeze a rights-cleared corpus and calibrate only on its training/calibration split.
6. Earn a production release through quality, operational and device gates.

No subscription-price comparison, synthetic fixture or sharpness metric by itself
establishes parity. Local zero API fee is not zero hardware/electricity/latency cost.

## 3. Architecture boundaries

The target separates ingest, precision base, region routing, texture generation,
candidate validation, protected composition, review and export. The currently
implemented regional review accepts supplied base/texture passes; it does not
complete the target one-click ingest-to-inference journey.

[Architecture](docs/project/ARCHITECTURE.md) distinguishes current modules from target
components. [Decisions](docs/project/DECISIONS.md) records the rationale, alternatives
and changes that require a new decision record.

## 4. Chapters and milestones

| Chapter | Deliverable | Exit |
| --- | --- | --- |
| M0 Foundations | F01-F03 | Scoped plan; tested compositor and reblend CLI |
| M1 Runnable alpha | F04-F07 | Persistent artifacts, selected base, one live texture workflow, durable async jobs |
| M2 Protected studio | F08-F11 | Accepted editor, confidence masks, structural protection and managed exports |
| M3 Quality beta | F12-F13 | Frozen corpus, held-out comparison and recorded defect decisions |
| M4 Production release | F14-F16 | Reliable batches, measured device budgets, packaging and signoff |
| M5 Optional expansion | F17 | A measured quality/cost reason for another adapter |

[Roadmap](docs/project/ROADMAP.md) supplies dependencies, checkpoint evidence and
parallel lanes. No calendar promise or project completion percentage is implied.

## 5. Current position

F01-F04 are implemented in an open feature PR, not released. F05-F08 have substantial
engineering work but remaining live/device/async acceptance. The 62-test local
snapshot is at `5f32fba`. The audited executor lacks model weights and a GPU worker.
Automatic segmentation, robust structural detection, managed high-precision export,
full benchmark acceptance and production packaging remain ahead.

A new documentation audit also records legacy pipeline/claim defects rather than
quietly treating historical claims as validated. See [Risks](docs/project/RISKS.md).

## 6. Operating model

GitHub is canonical for accepted specs, architecture, source, evidence and decisions.
[Linear](https://linear.app/melato/project/fidelis-studio-a057f366fa71) owns task
coordination. Keep F01-F17 stable across both. Owners/dates stay unset until real.
A task closes only when its scope's acceptance evidence exists; a partial adapter
or a protocol fixture does not close a live quality gate.

Another contributor starts with [Onboarding](ONBOARDING.md), claims a bounded work
item, reads [AGENTS.md](AGENTS.md), and uses [Contribution workflow](CONTRIBUTING.md).
Do not create a second competing task board in Notion or use hosting deployments
as a substitute for engineering coordination.

## 7. Final expectation

A creator can open a source, choose an honest profile, review masks and cost,
enhance with a verified workflow, adjust regions without paying for another pass,
inspect real pixels and export colour-managed masters with provenance. Batches
resume after interruption without duplicate generation. Limitations are visible.
Only the [quality and release gates](docs/project/QUALITY_GATES.md) can establish
that this expectation has been met.
