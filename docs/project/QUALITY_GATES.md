# Quality, operational and release gates

## Evidence levels

| Level | Evidence | Does not establish |
| --- | --- | --- |
| E0 Implemented | Code/graph exists with recorded SHA | That it runs or is available elsewhere |
| E1 Fixture/protocol tested | Deterministic tests, HTTP fixtures and failure cases | Real model fidelity or target-device latency |
| E2 Live inference verified | Actual weights/runtime, valid output and recorded settings | Creative acceptance or competitor parity |
| E3 Visual/device accepted | Reviewed images and actual device behaviour | General leadership outside the measured corpus |
| E4 Released | Merged, packaged, rollout/rollback and owner signoff | Unmeasured future quality/capability |

Current Studio snapshot has substantial E1 evidence. No live GPU quality/parity
certificate is claimed. Do not infer levels from a version string or old changelog.

## Gate order

1. **Integrity:** decoded image is valid; dimensions, orientation and intended
   alpha/colour contract match; no unintended invalid/uncovered tiles. Legitimate
   black image regions are not automatically failed inference.
2. **Fidelity:** no confirmed identity, logo/text, seam/zip, hardware or product-feature
   mutation. Exact protected compositor pixels match the base; the base itself can
   still contain model-induced errors and must be assessed.
3. **Appearance:** skin/fabric/hair are credible at fit, 100% and 200% inspection;
   no plastic skin, repeated pores/weave, background invention or HDR halos.
4. **Resources/reliability:** restart, timeout, cancellation, full storage, corrupted
   output and batch interruption have defined outcomes and no duplicate paid run.
5. **Release:** accepted scope, documentation, target-device measurements, model
   terms, package/upgrade/rollback and explicit creative/release signoff.

## Corpus and comparisons

The detailed plan proposes 60 licensed/consented cases across portraits, apparel,
textiles, macros and packshots/edge cases, frozen 30 calibration / 30 held-out.
Rights, hashes, critical ROIs, known text, output dimensions and recipes are recorded.
Existing few crops and synthetic fixtures are regressions, not this finished corpus.

Compare the same inputs/targets against interpolation, selected deterministic base,
current Fidelis, a VOSR challenger and dated Clarity/Krea outputs when access permits.
Keep each full-resolution output separate; include failures, actual cost and timing.
Missing comparator access is missing evidence, not a simulated result.

Blind randomized pairwise review records naturalness, structure, colour/background
restraint and publishability. The detailed plan's proposed threshold is >=80%
preference-plus-ties and >=50% wins per target, no category below 60%
preference-plus-ties, and no critical defects. Treat that as a proposed acceptance
protocol requiring release-owner agreement, not a proven product score. Report
sample counts and confidence intervals. Expand held-out evidence before broad
market-leadership claims.

PSNR/SSIM require an explicitly described reference; source-resized or downsampled
consistency is not ground-truth recovery accuracy. A gradient proxy must keep its
own name. Real LPIPS requires the actual implementation/model/version. Unsigned
JSON provenance must never be represented as a verified C2PA signature.

## Reproducibility receipt

Each quality run records source permissions/hash, code SHA, runtime/node versions,
weight hashes/terms, model graph, seed, all parameters, source/target sizes,
transform/registration assumptions, masks, colour path, elapsed cold/warm time,
peak measured memory, actual billed cost if any, output hashes and defect decisions.
No benchmark is promoted using just a successful process exit or wrapper status.

## Release checklist

- All required milestone exits and blocking defects resolved or explicitly excluded
  with a documented, scope-consistent limitation.
- Relevant Linux/macOS CI and target-device smoke evidence linked to the release SHA.
- Full image/native-pixel and colour/alpha round-trip checks, including protected ROIs.
- Worker/weight availability and compatible terms verified; secrets/images excluded.
- Async cancellation/restart and no duplicate generation demonstrated for included backends.
- Resource/cost budgets measured, not extrapolated from fixture timing.
- Installation, upgrade, backup/export and rollback verified for the packaged path.
- Owner receives concrete comparison evidence and makes the final creative/release judgment.

The [explicit corpus lane](../BENCHMARK_CORPUS.md) now audits available assets and
refuses premature freeze. Its current inventory does not satisfy the 60-case gate.
