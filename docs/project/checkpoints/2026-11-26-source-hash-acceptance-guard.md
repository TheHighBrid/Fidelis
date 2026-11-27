# Source-SHA split enforcement in quality acceptance and audition · issue #134 · 2026-11-26

Scope claimed from `main` (`5641e94`, after PR #138 merged) on
`work/f13-source-hash-134`: extend source-hash split-isolation enforcement into
`fidelis/eval/quality_acceptance.py`, `scripts/evaluate-quality-acceptance.py`,
`fidelis/studio/audition.py`, `fidelis/eval/blind_review.py`, and
`scripts/audition-melato.py` so aliased `case_id` / `asset_id` records sharing
a calibration or cross-split source SHA-256 cannot evade held-out split checks.
No frozen manifest labels, thresholds, weights, or historical artifacts were altered.

## Changes made

- `fidelis/eval/source_split_preflight.py`: Added `collect_source_split_index`
  reusing `_scan_manifests` to build `sha_by_id`, `calibration_shas`,
  `held_out_shas`, `conflict_shas`, `aliases_by_sha`, and `id_hash_conflicts`,
  and extended `_alias` to validate flat `sha256` alongside `source.sha256` and
  `source_sha256` (rejecting any disagreement).
- `fidelis/eval/quality_acceptance.py` & `scripts/evaluate-quality-acceptance.py`:
  - `evaluate_held_out_acceptance(..., manifest_paths=None)` and CLI `--manifest`
    (repeatable) validate source-SHA split isolation via `collect_source_split_index`.
  - Calibration summaries now accept and validate `source_sha256s` and
    `case_source_hashes`; held-out ballots validate `source_sha256` / `source.sha256`
    and compare against manifest SHAs (rejecting malformed or disagreeing hashes).
  - Aliased held-out IDs matching a calibration or cross-split-conflicted source
    SHA-256 fail closed with `split_contamination_detected`, `overall_status="failed"`,
    and structured `calibration.source_sha_contamination` diagnostics.
- `fidelis/studio/audition.py`, `fidelis/eval/blind_review.py`, & `scripts/audition-melato.py`:
  - `audition_report.json` cases and `blind-answer-key.json` pairs now record
    measured `source_sha256`; `audition_receipt.json` records `source_case_hashes`.
  - Added `--split-preflight-manifest` (repeatable) and `--enforce-split-isolation`
    to `scripts/audition-melato.py`, failing closed before inference if any selected
    case participates in a cross-split source-SHA conflict.

## Verification

- Targeted tests: `tests/test_source_split_preflight.py`,
  `tests/test_quality_acceptance.py`, `tests/test_model_audition.py`,
  `tests/test_cached_png_and_raw_checkpoints.py`, `tests/test_melato_protocol.py`.
- Full repository suite: `unittest discover`, `pytest tests/e2e/`,
  `tests/test-web-ui.sh`, `tests/smoke-test.sh`, `tests/test-release-pipeline.sh`,
  `git diff --check`.

## Remaining gates

- Issue #134 historical source-evidence resolution & remaining 15/60 corpus slots (`F12`).
- Full 198.7 MP `tex_cotton_twill_chino` raw-checkpointed evaluation run on `main` (`#129` / `#135`).
- External hardware/human gates: live GPU ComfyUI SDXL workflow (`F06` / `MEL-60`),
  Clarity/Krea comparator outputs & 30-case blind dual-reviewer ballots (`F13`),
  physical Android/iOS touch review (`F08` / `MEL-59`), and owner release signoff (`F16`).
