# Fidelis contributor and agent directives

These directives apply to this repository. They supplement the user's current
instructions and the existing rules under `.agents/rules/`.

## Read before editing

1. `ONBOARDING.md` and `docs/project/HANDOFF.md`.
2. `docs/project/STATUS.md`, `docs/project/RISKS.md`, and the relevant Linear task.
3. `PLAN_BLUEPRINT.md` and the relevant architecture/quality sections.
4. Any more specific instructions inside the files/area you will change.

Determine the branch before assuming a module exists. Studio code is in PR #12
on `feat/region-aware-studio` until merged. `main` documentation can describe that
unmerged implementation; it must not imply deployment or release.

## Objective and invariant order

Preserve identity, geometry, text/logos, garment construction and hardware first;
then improve believable skin/hair/material detail; then optimize speed and cost.
Do not optimize sharpness as a substitute for photographic realism.

- Unknown or low-confidence regions remain on the precision base.
- Explicit protection wins over semantic texture masks. Fully protected pixels
  remain exactly equal to base pixels after composition and finishing.
- Exact dimensions do not prove internal registration. Reject unexplained crop,
  orientation, output-size or encoding changes; never silently resize them away.
- Reconstructed micro-detail is synthesis, not recovered evidence.
- No default grain, aggressive sharpening, beauty smoothing or face restoration
  to conceal a quality failure. Retain the rejected Nomos/source-fusion history.
- One output image per file. No collages, contact sheets or combined concepts.

## Evidence and communication

Separate implemented, unit/protocol-tested, live-inference-verified,
visually-accepted, merged and released. Never report any as another.
A passing fixture is not model quality evidence. Do not fabricate benchmark
scores, model availability, GPU timings, costs, completion percentages or signoff.
Do not label a gradient proxy LPIPS or an unsigned JSON sidecar verified C2PA.
Historical README/changelog claims do not override the current evidence ledger.

## Work independently without collisions

Use one issue per bounded deliverable, one branch/worktree per active contributor,
and one accountable owner per issue. Claim scope before editing and record the
base SHA, files/interfaces touched, acceptance criteria and dependencies.
Do not reset, overwrite or discard another contributor's working changes. Parallel
work is allowed where interfaces and file ownership are separated; do not create
extra agents unless the user/task instructions authorize it.

Keep changes additive and preserve the working native CLI. Do not replace the
current studio with an unrelated framework, silently change storage contracts,
swap models, or import a different submission/state engine under a small task.
Propose architecture changes through an ADR and their real migration/test impact.

## Python and verification

Use the repository `.venv` when present. Shell wrappers must resolve its Python;
Python subprocesses use `sys.executable`. Read and follow
`.agents/rules/python-environment-integrity.md` and
`.agents/rules/companion-telemetry-contracts.md`.

Run the checks relevant to the change. For Studio behaviour, the baseline is:

```bash
.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v
PATH="$PWD/.venv/bin:$PATH" bash tests/test-web-ui.sh
PATH="$PWD/.venv/bin:$PATH" bash tests/smoke-test.sh
git diff --check
```

JS changes also require syntax checks and relevant history/brush parity coverage.
Do not repeatedly rerun broad checks once the relevant checks pass unless a new
change or unresolved failure justifies it. Visual/device acceptance remains a
separate record; never claim it from source inspection.

## Runtime, privacy and resources

Keep current Studio access local and bind explicitly to `127.0.0.1`. No public
hosting of its local filesystem/job routes. Do not add a cloud fallback that sends
images merely because a local worker is offline. Paid/remote execution must follow
an explicitly selected provider and budget policy. Keys never enter code, browser
bundles, logs, issue bodies or examples. Do not copy real credentials into docs.

No guessed checkpoints, fabricated LoRAs, unpinned remote model code or hidden
interpolation fallbacks. Checkpoint bytes, graph hashes, node/runtime revisions,
terms and target-device behaviour are separate verification obligations.
An uncertain submission must not be repeated automatically. Preserve run/prompt
IDs and reconcile actual queue/history state.

## Blockers and handoff

Before asking the owner to act, inspect available logs, code, artifacts and prior
attempts. Do not restart known failed experiments or use the owner as a test loop.
Bypass disposable blockers and continue independent authorized work. If a gate
requires unavailable hardware/access, record the precise missing capability and
finish the independently verifiable implementation first.

At handoff update the task, relevant docs and evidence: commit/branch, what changed,
checks/results, known limits, remaining acceptance, and the next concrete action.
Update `docs/project/STATUS.md` and the committed task snapshot when their facts
change. Link to evidence instead of narrating abandoned attempts.
