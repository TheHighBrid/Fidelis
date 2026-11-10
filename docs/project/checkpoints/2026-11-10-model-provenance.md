# Model provenance & usage-terms checkpoint · 2026-11-10

## Scope and delivery

F05-B / MEL-75, based on `10a30950c93783729d0c051fa84e7effd74011dc`
(`origin/feat/region-aware-studio`). Isolated branch:
`work/mel-75-model-provenance` (`--no-track`). Requires no GPU inference or model
downloads; PR review/merge and remote Linear `MEL-75` sync remain pending. Parent
`F05` (`MEL-58`) retains live runtime qualification on target hardware.

## Implemented result

- Added `config/model-provenance-v1.json` recording explicit sources, pinned vs.
  unpinned upstream revisions, SHA-256 byte pins (when pinned), and separate
  commercial/distribution usage terms across 2 runtimes and 11 models (`native_ncnn`,
  `portrait_onnx`, `studio_generative`, `studio_segmentation`).
- Kept missing/unpinned upstream checkpoints (`4x-UltraSharp`, `yunet`, `codeformer`,
  `sdxl-comfy-texture-slot`, `clarity-upscaler-ref`, `flux-1-dev`,
  `segformer-b2-clothes`, `ESRGAN-Nomos8kSC`) explicitly uncertified and never
  marked restricted/unpinned terms (`AGPL-3.0`, `FLUX.1-dev Non-Commercial`,
  `S-Lab-1.0`, `other`) as `production_terms_cleared`.
- Added `fidelis/studio/provenance.py` (`validate_provenance_catalog`,
  `audit_model_provenance`, `load_tsv_candidates`) enforcing fail-closed parity
  with `config/photo-candidates.tsv`, valid SHA-256 checksums, terms-before-clearance
  gates, and non-certification until real F05/F13 evaluation.
- Integrated `model_provenance` into `fidelis/studio/capabilities.py` (`inventory`)
  while preserving existing `candidates` / `registered_models` fields, and added
  CLI validator `scripts/audit-model-provenance.py`.
- Updated `docs/PHOTO_MODEL_CANDIDATES.md` to separate historical NCNN crop notes
  from Studio certification, added 5 regression tests in `tests/test_model_provenance.py`,
  and wired provenance checks into `.github/workflows/ci.yml`.

## Verification

- `.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v`: passes
  all 114 baseline tests plus 5 new tests in `tests/test_model_provenance.py`
  (**119 total tests**).
- `.venv/bin/python scripts/audit-model-provenance.py`: verifies TSV cross-check
  and inspects `FIDELIS_HOME` on disk (local matched vs. unpinned vs. missing)
  without inferring inference certification.
- Existing `tests/test-web-ui.sh`, `tests/smoke-test.sh`,
  `tests/test-photo-candidate-installer.sh`, `json.tool`, `py_compile`, and
  `git diff --check` verified after final edits.

## Remaining limits and next action

- Upstream download scripts (`scripts/install-macos-runtime.sh` and `Dockerfile`)
  still download `realsr-ncnn`, `realesrgan-ncnn`, `yunet.onnx`, and
  `codeformer.onnx` without SHA-256 pins; pinning those release assets remains
  installer/packaging work (`F05-A` / `F15`).
- Studio generative texture checkpoints (`sdxl`, `flux`, `segformer`) require real
  selected weights, SHA hashes, license clearances, and live worker output under
  `F05` / `F06` / `F09` / `F17`.
- Next independent work without GPU: `F08-B` (`MEL-80` reachable browser/device
  visual acceptance) and `F12` real cleared photography acquisition.
