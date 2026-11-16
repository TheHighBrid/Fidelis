# Browser acceptance gate integrity · 2026-11-16

## Scope

MEL-80 / F08-B follow-up from Studio base `5fa52920d3a7e114faacab4c3cb121977e97b63a`.
This change affects the acceptance runner and its evidence, not the editor, model,
or regional storage. Retain the previous macOS browser result as historical evidence.

## Findings and correction

- The runner reported `observed_defects` without necessarily returning a failing exit
  status. Now a completed receipt includes `acceptance_passed` and `failed_checks`;
  false or invalid checks, nonzero error counts, and any observed defect fail the gate.
  Runtime and HTTP error details are retained in the receipt.
- The previous HTTP listener ignored every 409. Only the single expected stale-save
  conflict on the tested job is exempt; the gate requires its actual receipt and
  checks the editor still holds the original revision and unsaved stroke.
- The report formerly claimed macOS irrespective of host. The limitation now uses
  the actual OS and architecture. CDP connects and commands have timeouts; closed
  transports reject pending commands and already terminated children are not awaited.

## Verification

- `node --test tests/test_browser_acceptance_report.mjs`: 8 passing tests on Node 24.22.1.
- `node --check scripts/browser-acceptance.mjs`, shell syntax, static smoke, workflow
  YAML parse, and `git diff --check`: passed.
- Full browser attempt on Linux x64, Chromium 156.0.8078.79: Chromium aborted with
  SIGABRT before DevTools startup; runner returned exit 1. No browser acceptance
  receipt, new visual approval, or target-device evidence is claimed. The earlier
  macOS evidence is unchanged.

## Remaining gate

Run the revised real-browser harness on a supported same-host Chromium installation,
then record physical Android/iOS touch and stylus interactions and human visual
signoff. The dedicated CI workflow tests the report/transport contract only; it is
not a physical-device or photographic quality gate.
