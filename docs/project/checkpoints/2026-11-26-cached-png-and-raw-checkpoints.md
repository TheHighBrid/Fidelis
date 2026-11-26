# Cached full-grid PNG validation and raw inference checkpoints · issue #135 · 2026-11-26

Scope claimed from `main` (`6b47a8d`) on `work/f13-raw-checkpoint-135`: validated
cached generated PNG inspection/decoding without altering global Pillow limits,
plus atomic post-inference/pre-guard raw checkpoint persistence and fail-closed
replay. No acceptance thresholds, model weights, corpus splits, or public
upload/import limits were relaxed.

## Cached full-grid PNG validation (`fidelis/studio/png.py`)

- Added `inspect_cached_generated_png` and `read_cached_generated_png` requiring
  explicit `expected_size=(width, height)` and `expected_mode` (`"RGB"`/`"RGBA"`).
- Validates PNG signature, `IHDR` dimensions/depth/color type/CRC, absence of
  `acTL` (APNG), `tRNS`, `iCCP`, and untagged non-sRGB `gAMA`/`cHRM`, plus
  `IDAT` presence and complete `IEND` with zero trailing bytes.
- Decodes via `cv2.imread(..., IMREAD_UNCHANGED)` (or pure-Python zlib/scanline
  fallback when `cv2` is unavailable) without touching `Image.MAX_IMAGE_PIXELS`.
- Public upload/import limits remain unchanged (`scripts/web-ui.py` 16 MP,
  `read_rgb8_png` / `read_export_pass` / `inspect_image` 40 MP, Pillow default
  limit intact).
- Verified with `Image.MAX_IMAGE_PIXELS` patched to `1000`: ordinary `Image.open`,
  `read_rgb8_png`, `read_export_pass`, and `inspect_image` still raise
  `DecompressionBombError`/`PngPixelLimit`, while `inspect_cached_generated_png`
  and `read_cached_generated_png` succeed cleanly.
- Verified on the actual preserved `17404×11416` (198.7 MP) twill artifacts
  (`candidate_4x.png` and `bicubic_4x.png`) under
  `~/melato-corpus/fidelis/release-evidence/53f1995/twill-swinir/cases/tex_cotton_twill_chino/`:
  both still trigger `Image.DecompressionBombError` under Pillow `Image.open`
  and validate cleanly via `inspect_cached_generated_png`.

## Resumable raw inference checkpoints (`fidelis/engine/checkpoints.py`, `fidelis/engine/checkpoint_replay.py`)

- Added `raw_checkpoint_callback` inside `RestorationRunner.run()` immediately
  after `backend.restore()` + `_enforce_exact_shape()`, before texture guard
  masking, `compose_regions()`, or `screen_internal_drift()`.
- `save_raw_checkpoint` / `make_raw_checkpoint_callback` atomically persist
  `raw_candidate.npy` and exact `bicubic_base.npy` first (`allow_pickle=False`),
  then atomically write `checkpoint_receipt.json` last.
- Receipt binds: `case_id`, `source_file_sha256`, `source_pixel_sha256`,
  `source_shape`, `scale`, `target_shape`, `model_id`, original `backend`,
  `weights_sha256`, `runtime` + `runtime_sha256`, `options` + `options_sha256`,
  `normalized_rois` + `normalized_rois_sha256`, `protocol_sha256`,
  `config_sha256`, `generation_identity` (`code_commit`, `working_tree_dirty`,
  `file_hashes`), and separate artifact roles/paths/shapes/dtypes/bytes/SHAs.
- Added `CheckpointRestorationBackend` (`backend="checkpoint"` /
  `checkpoint_replay` and `--replay-checkpoint-dir` on `scripts/audition-melato.py`):
  replays without loading or calling any inference backend, validates `.npy`
  headers (`uint8`, C-order, exact shape, exact file extent), `allow_pickle=False`,
  mmap reads, file/pixel SHA-256s, and all bound identities.
- Rejects partial publication, path escape (`..`, absolute paths, symlinks),
  guarded `candidate_4x.png` or non-`raw_candidate` roles, and any bound
  identity mismatch without fallback. Preserves `original_generation_identity`
  separately from `evaluation_identity` and sets `inference_executed: false`.

## Verification

- `tests/test_cached_png_and_raw_checkpoints.py` (6/6 passed, including injected
  post-inference failure recovery, preserved `FAIL_SHARPENING_ONLY` behind
  locked `preserve` ROIs, CLI save/replay round-trip, low Pillow limit test,
  198.7 MP preserved twill PNG check, and tamper/escape/partial-pub rejections).
- Full `unittest discover -s tests -p 'test_*.py' -v`: **661/661 passed**.
- `tests/test-web-ui.sh`, `tests/smoke-test.sh`, `tests/test-release-pipeline.sh`,
  and `git diff --check`: all passed.

## Remaining gates

- This closes the software/checkpoint engineering scope on #135; full 198.7 MP
  twill raw generation + quality evaluation (`#129`), corpus split/exposure
  resolution (`#134`), live ComfyUI GPU SDXL qualification (`F06`), 60-case
  corpus completion & comparators (`F12`), blind human review (`F13`), physical
  mobile review (`F08`), and owner release signoff (`F16`) remain open.
