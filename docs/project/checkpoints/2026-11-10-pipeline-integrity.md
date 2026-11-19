# Pipeline integrity checkpoint · 2026-11-10

## Delivery and scope

Implemented on `feat/region-aware-studio`, based on `f95f5772f96e0059651f86b8dadc22dad73265ca`, for [PR #12](https://github.com/TheHighBrid/Fidelis/pull/12).
The delivery commit is the commit containing this receipt. D01-D04 are In Review,
not released. The audited main runtime still predates these fixes until merge.

| Item | Change | Regression evidence |
| --- | --- | --- |
| D01 / MEL-73 | Unsigned execution JSON no longer reports verified signatures; atomic optional sidecar writes and explicit unsigned telemetry | Sidecar hashes/status, CLI output, spans and failed sidecar write |
| D02 / MEL-72 | Removed invalid tiled-module import; propagate the selected executable through the real tiler subprocess | Large-input round trip with a controlled executable, spaces in paths, runtime errors and wrong output dimensions |
| D03 / MEL-71 | Default HTTP bind and Compose host publication use loopback; deployment helper no longer opens firewall ports or advertises a public service | CLI/env/programmatic bind tests, Compose assertions and deployment script with fake commands |
| D04 / MEL-74 | Removed invented numeric quality fallbacks and pseudo-LPIPS; corrected RGB ordering, physical CIE76 Lab and reference semantics | Missing decode/method/reference cases, paired reference, measured colour values, telemetry and CLI serialization |

## Contract changes

- `metric_context.schema_version=2` records availability and reference. Default
  comparisons downsample output to source and are **source consistency**, not
  evidence of recovered true detail. `--ground-truth` requests a paired reference
  at native output dimensions; missing/mismatched references yield null metrics.
- Unavailable metrics are JSON null. LPIPS and legacy `lpips_proxy` remain null
  because no actual LPIPS implementation ran. `gradient_distance_proxy` names
  the gradient-derived measurement honestly. Consumers must support nullable values.
- CIE76 Delta E now uses physical float Lab units. Old encoded-Lab thresholds or
  historical colour scores need corpus recalibration before quality certification.
- The legacy provenance function name and `.c2pa.json` suffix remain for compatibility.
  Content is an unsigned execution record with `application/json`, no signing issuer,
  and no signed/conformant C2PA claim. Optional sidecar failure is reported explicitly.
- Telemetry uses a bounded two-second timeout. Millisecond timing aliases carry an
  explicit unit. A telemetry outage does not convert a completed image into failure.
- Explicit `HOST`/`--bind` overrides remain deliberate options. Containers retain
  internal `0.0.0.0` binding for forwarding, with host publication only on
  `127.0.0.1:8080`. Regional client-loopback checks remain enforced; bridge clients
  may be rejected. Use a same-host local process for the regional editor until a
  reviewed container trust design exists. A tunnel alone does not bypass that check.

## Verification

- Full Python discovery: **77 passed**. Includes 11 pipeline-integrity tests and
  four local-default/deployment tests, added to CI.
- Existing static smoke, fidelity metrics, release-packaging fixture and web UI
  HTTP integration checks passed. Release packaging used fixture version `3.9.9-test`;
  it did not publish a release or certify bundled model weights.
- Python compilation, deployment shell syntax and `git diff --check` passed.
- Documentation links, task IDs/dependencies and issue-form YAML validated.

Controlled executables and protocol fixtures verify orchestration and measurement
contracts. No live model inference, paid cloud request, Docker build/deployment,
M1/Android memory or visual quality acceptance was performed. The legacy full
pipeline instrumentation shell test requires a real runtime and was not run;
its unsigned-status expectation was corrected. Remote CI is separate evidence.

## Next action

Review/merge D01-D04 with their nullable-metric compatibility change. Continue
F07-A bounded asynchronous jobs/cancellation and F08-A native-pixel crop inspection
as independent scoped work. Live F05/F06 acceptance still requires compatible
weights and a reachable worker; do not claim competitive parity from fixtures.
