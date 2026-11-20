# F09 / MEL-62: confidence routing contract checkpoint

Date: 2026-11-19. Base: main at 1c954cd5d3b949c124b467228669213a50d47355.
Branch: `work/mel-62-confidence-routing-contract-20261119`.
Scope ownership: `fidelis/studio/confidence_routing.py`, `tests/test_confidence_routing.py`, this checkpoint only.

## Implemented
A deterministic, zero-network, NumPy-only candidate mask router. Requires exactly skin, hair and fabric probability maps plus explicit protection on the same pixel grid. Invalid dimensions, NaN, infinity, out-of-range values, invalid thresholds and missing classes fail closed. Unknown/background, weak or tied classifications contribute no generated pixels. Optional confidence attenuates texture contribution. Hard protection wins. No inference, resizing, storage or Studio API changes.

## Evidence and limits
Ten focused Python unittest cases passed in a local isolated source-equivalent harness; syntax compilation passed. The full repository test suite and hosted CI are separate gates. This does not qualify a segmentation model, prove semantic classification quality, or integrate automatic masks into the Studio editor. It does not replace the compositor's final exact-pixel lock enforcement.

## Next
After PR #64 integrates Studio, wire these suggested masks into the existing review flow without overwriting manual protect strokes. Benchmark calibrated confidence and structural failure modes on rights-cleared material, and require manual confirmation of logos, seams and hardware. Do not mark F09 complete before those gates.
