# F10 / MEL-64: structural drift quality remediation

Base `b03100192544024f56646c91ee560b8857de7e1c` (integration PR #64). Scope:
`fidelis/postprocess/roi_protection.py`, its regression tests, and this contract.
No queue, UI, model, packaging, scanner-policy or other contributor changes.

- Split ROI validation, mask construction, patch measurement, block screening,
  per-ROI classification and final verdict into bounded functions.
- Reject non-finite, reversed or out-of-range thresholds and invalid integer
  settings before any drift screen. Constrain translation loops to in-grid
  candidates without changing search order or valid-match outcomes.
- Local Radon cyclomatic complexity: `screen_internal_drift` 62 -> 7;
  `build_roi_protection_masks` 28 -> 4; `validate_rois` 23 -> 9.
- All eight ROI tests, including previously failing invalid-setting subcases,
  pass. Differential local checks against the base matched every field and
  mask for 48 drift cases and 24 protection-mask scenarios. Ruff passes for
  the changed module; static smoke and web UI tests pass.

This is engineering/fixture evidence only. Hosted CI and Codacy are separate
review gates. MEL-64 remains partial pending production-corpus structural and
visual acceptance; no live model output, OCR accuracy or release claim is made.
