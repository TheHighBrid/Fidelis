# 198.7 MP twill raw-checkpointed evaluation · issues #129 & #135 · 2026-11-27

Base: clean `main` (`b414a905337719ab1db2163641d9ea41beb36463`, `working_tree_dirty: false`).  
Target case: `tex_cotton_twill_chino` (`calibration`, `textiles`, source `cc0_wikimedia_chino_twill_dsc02850.jpg`, `4351×2854` RGB uint8, source file SHA-256 `eca7ad1ab4f540d9efbcd2b37eeb86a705ad8b96be63ba7ed63ce3c6541cc55f`, pixel SHA-256 `4240df676be49506b9f61f9b7e18c0f1b029679a5a5ea2cc04e956f48c583f98`), 4× target `17404×11416` (`198,684,064` pixels).  
Off-repo artifacts:
- Raw checkpoint: `~/melato-corpus/fidelis/release-evidence/b414a90/twill-swinir-raw/raw_checkpoints/tex_cotton_twill_chino/`
- Replay & evaluation: `~/melato-corpus/fidelis/release-evidence/b414a90/twill-swinir-replay/`

## 1. Raw MPS inference & atomic checkpoint (`2026-11-27T09:02:16Z`)

- Executed `scripts/audition-melato.py` with `--backend torch_spandrel --torch-device mps --tile-core 192 --tile-context 32 --model-id swinir-lightweight-div2k-x4` (`345` tiles, `002_lightweightSR_DIV2K_s64w8_SwinIR-S_x4.pth`, SHA-256 `09fad24e32ae62722e1a055efde9921328f4137981bab0a42a4a3a806306c58e`) and `--raw-checkpoint-dir`.
- Persisted raw checkpoint atomically before downstream evaluation was interrupted by a host server restart:
  - `raw_candidate.npy`: `596,052,320` bytes (`11416×17404×3` `uint8`, file SHA-256 `e1cc1735e0a09e3cd0e7440bac9403cf4d1863aff6f46b13d5e2da94126b9034`, pixel SHA-256 `1bc1b9c9887e4a03dcd48bf00ef1b783c25c5ee14c3d55d3d9c5bfe06321b335`)
  - `bicubic_base.npy`: `596,052,320` bytes (`11416×17404×3` `uint8`, file SHA-256 `bd6d15a733bf4192f4df011af7c3fd222ce183fe9837e214c90cbeb59b7338ec`, pixel SHA-256 `983386bba25b2864dd90b4570339ad240f64f3faaefbb3cbb562c99d3adc82c9`)
  - `checkpoint_receipt.json`: SHA-256 `52a7c3101ef76a62200dfd3ed99c0d2e8afd9e5c9bdce9997eabcb6634dc2f95`, binding `code_commit: b414a905337719ab1db2163641d9ea41beb36463`, `working_tree_dirty: false`, and `diagonal_wale` ROI (`[2612, 1712, 12180, 7992]`).

## 2. Resumed checkpoint replay & bounded native-grid evaluation (`2026-11-27T20:11:04Z` -> `20:30:47Z`)

- Resumed cleanly via `--replay-checkpoint-dir` under `.venv/bin/python` (`Python 3.11.17`, `NumPy 2.0.2` `complex64` FFT, `inference_executed: false`, `checkpoint_replayed: true`) with `--split-preflight-manifest experiments/melato_corpus_manifest.json --blind-split calibration --evaluate-acceptance`.
- Measured `/usr/bin/time -l` resource metrics on Apple M1 (`8 GB` unified RAM):
  - Wall-clock duration: **`1195.33 s`** (`491.34 s` user, `154.43 s` sys)
  - Peak RSS (`maximum resident set size`): **`2,769,731,584` bytes (`2.58 GiB`)**, `0` process swaps
- Outcome (`audition_report.json`): **`PASS_MATERIAL_DETAIL`** (`1/1` passed):
  - **Drift screening**: `PASS` (`194,208` blocks evaluated, `0` flagged, `max_block_shift_px: 0.0`, `min_block_coherence: 0.9031`, `locked_pixel_mismatches: 0`; `diagonal_wale` `candidate_edge_coherence: 0.9849`, `candidate_shift_px: 0.0`)
  - **F2 interior texture**: `interior_texture_variance_ratio: 1.515784`, `interior_midband_energy_ratio: 1.767068`, `interior_pixel_count: 53,538,427`, `passed: true`
  - **F3 oversharpening restraint**: `contour_overshoot_mean: 0.085335`, `contour_overshoot_p95: 0.212601`, `contour_overshoot_frac: 0.014298`, `contour_nyquist_to_midband_ratio: 0.0102`, `contour_nyquist_gain_vs_bicubic: 0.796678`, `contour_pixel_count: 21,412,645`, `passed: true`
  - **F4 fabric weave (PR #133 reference precision)**: `weave_orientation_coherence: 0.981975`, `weave_fft_coherence: 1.000002`, `weave_energy_ratio: 1.015712`, `passed: true`
- Saved outputs & cached PNG validation (`fidelis/studio/png.py`):
  - `candidate_4x.png`: `133,218,709` bytes, `sha256: 244d1b1f4750b4a932fdea0cf1793ba54ae649d2fb63c056ddc57f416e496f2b`, `inspect_cached_generated_png(..., verify_crc=True)` confirmed `[17404, 11416]` RGB8 `iend_complete: true` while default Pillow `Image.open` raises `DecompressionBombError` (`198,684,064 > 178,956,970`).
  - `bicubic_4x.png`: `118,901,757` bytes, `sha256: 48145cbf49a2d0d07e3cb41ae61975d179c6ced4cca2f0e3b2842b650435b884`, `inspect_cached_generated_png(..., verify_crc=True)` confirmed `[17404, 11416]` RGB8 `iend_complete: true`.
  - Saved 8 paired native 100%/200% `full_frame` and `diagonal_wale` PNGs plus `audition_report.html`, `audition_receipt.json`, `blind-ballot.json`, `blind-answer-key.json`, and `acceptance_summary.json`.

## 3. Honest scope & remaining gates

- `audition_receipt.json` records `evidence_scope: "unfrozen_diagnostic_no_human_review"` and `code_sha: "b414a905337719ab1db2163641d9ea41beb36463"`.
- `acceptance_summary.json` sets `automated_detail_gates.passed: true` and `overall_status: "failed"` (`corpus_lock_sha256` missing, `recipe_frozen: false`, `ballots: []`, `owner_creative_signoff: pending`, `12` cross-split manifest conflicts in `source_split_preflight`).
- This closes the execution/resource/checkpoint engineering gates for **#129** and **#135** on `main` (`>= b414a90`). Remaining `E2..E4` gates stay open: `#134` owner manifest split/slot reconciliation (`12` conflicts, `mel_032` master recovery, `14/60` corpus slots), `F06`/`F05`/`F07` live ComfyUI SDXL GPU workflow & commercial model license clearance, `F12` paid Clarity/Krea comparator runs, `F08`/`F15` physical Android/iOS touch QA, and `F13`/`F16` 30-case blind dual-reviewer ballots & dual-owner release signoff.
