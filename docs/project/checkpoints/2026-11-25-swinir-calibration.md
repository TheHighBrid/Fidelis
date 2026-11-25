# SwinIR lightweight calibration diagnostic

No preset, release scope or acceptance criterion changed. Official upstream
release `v0.0` supplied `002_lightweightSR_DIV2K_s64w8_SwinIR-S_x4.pth`,
17,225,941 bytes, SHA256
`09fad24e32ae62722e1a055efde9921328f4137981bab0a42a4a3a806306c58e`.
Source: https://github.com/JingyunLiang/SwinIR/releases/tag/v0.0
Repository license: Apache-2.0, https://github.com/JingyunLiang/SwinIR/blob/main/LICENSE
Model/training-data terms remain a separate production review.

Actual inference on Apple M1 MPS, Torch 2.15.0, Spandrel, approved calibration
mel_014 source SHA `bd1249a6e7ea02a231d199035a578d1b391815f8e57389aec2de1c28ebacb91b`:
331×494 input to 1324×1976 output, model-only synchronized time 19.2406 seconds.
Output SHA256 `ae0f84ab38c7b22df6e6cb6b24ae715fb251c9c61017e2d2061bf02e4d7d0e70`.
The source contains existing graphic overlays; this is a diagnostic only.

Imported output was evaluated with the same predeclared mel_014 calibration ROIs,
4× bicubic baseline and unchanged protocol as the earlier RealeSR diagnostic.
Result: `PASS_MATERIAL_DETAIL` (one case); full acceptance still reports
`blocked_incomplete_evidence`. No held-out tuning or human scores were used.
This does not qualify SDXL, general fashion/product quality or release approval.

Private evidence root:
`/Users/tyf12/melato-corpus/fidelis/release-evidence/model-candidates/swinir-light-x4/`
contains separate full-resolution model/bicubic images, weight file, executable
reproduction script, timing/hash receipt and `audition/` report/crops/blank ballots.

## Velvet calibration comparison (`mel_028`, 2026-11-25)

Actual tiled inference on Apple M1 MPS (`Torch 2.15.0`, `spandrel 0.4.2`,
`tile_core=192`, `tile_context=32`, 45 tiles, no blending or resizing) ran on
declared `calibration` velvet trouser subject `mel_028`
(`509182202_1792638061047024.jpg`, SHA256
`0364bfe24b312294991caebaf57c877a37a89d9c9dd654630f5f4c1af5068b4f`):
`941×1672` input to `3764×6688` output, model-tiles synchronized time `90.2888 s`,
API cost `$0`.
Output SHA256 `483700f9e75437ad7f82533c446cfe7f4fc8dd931f1fe00cbdf4419ea1e36120`.

Evaluated via `scripts/audition-melato.py --manifest experiments/melato_corpus_manifest.json --select-id mel_028 --backend imported --evaluate-acceptance` against the unchanged `mel_028` manifest ROIs (`stripe_seam`, `shoe_construction`, `velvet_interior`) and `4x` bicubic baseline:

- Outcome: `PASS_MATERIAL_DETAIL` (`all_detail_gates_passed: true`)
- Locked ROIs (`stripe_seam`, `shoe_construction`): `0` locked pixel mismatches (`candidate_max_abs_diff: 0`, `candidate_edge_coherence: 1.0`, `candidate_shift_px: 0.0`)
- Interior texture: `interior_texture_variance_ratio: 1.816223`, `interior_midband_energy_ratio: 2.226106` (`passed: true`)
- Oversharpening restraint: `contour_overshoot_mean: 0.003176`, `contour_overshoot_frac: 0.000441`, `contour_nyquist_gain_vs_bicubic: 1.026539` (`passed: true`)
- Fabric weave (`velvet_interior`): `weave_orientation_coherence: 0.92065`, `weave_fft_coherence: 0.994782`, `weave_energy_ratio: 1.228235` (`passed: true`)
- Drift report: `PASS`, `0 / 24,662` blocks flagged, `max_block_shift_px: 0.0`
- Acceptance summary: `blocked_incomplete_evidence` (single calibration case; no held-out ballots or human creative signoff).

Preserved comparator context on the exact same `mel_028` calibration ROIs (`docs/APPLE_M1_PRECISION_BASE_AUDITION.md`): `RealeSR-general-v3` (`FAIL_SMOOTHING_REGRESSION`), `RealSR-DF2K` (`FAIL_FAITHFULNESS`), and `ESRGAN-Remacri` (`FAIL_SHARPENING_ONLY`).

Private velvet evidence root:
`/Users/tyf12/melato-corpus/fidelis/release-evidence/model-candidates/swinir-light-x4/velvet/`
contains `mel_028_calibration.png`, `bicubic_4x.png`, `receipt.json`, and
`audition/{audition_report.json,acceptance_summary.json,blind/,cases/}`.
`TorchSpandrelRestorationBackend` (`fidelis/engine/restoration_runner.py`) and
`scripts/audition-melato.py` (`--torch-device`, `--tile-core`, `--tile-context`)
now also support bounded overlapping-context tiling and `auto` device resolution.

Next: broader multi-case calibration across remaining `apparel_model`/`textiles`/`macros`
subjects, training-data/model terms review beyond the Apache-2.0 repository license,
and 60-case corpus / dual-reviewer held-out evaluation (`F12`/`F13`) before any
model or preset promotion.

## Multi-category calibration comparison & terms review (`2026-11-25`)

Executed side-by-side calibration runs via `scripts/audition-melato.py --manifest experiments/corpus_manifest.json --master-root ~/melato-corpus/fidelis --split calibration --evaluate-acceptance` (from pre-audit manifest `f17842d`) for both `SwinIR-lightweight-DIV2K-x4` (`torch_spandrel`, Apple M1 MPS, `tile_core=192`, `tile_context=32`, `$0`) and `RealeSR-general-v3` (`realesrgan_ncnn_vulkan`, `$0`) on frozen `macros` calibration case `mac_two_way_brass_zip` and the `cc0_polyhaven_wool_boucle_2k.jpg` looped-knit upholstery candidate (`0` locked pixel mismatches across all runs; note `tex_boucle_tweed` was restored to `missing` in `1e28ab8`, so the Poly Haven `wool_boucle` run is preserved as a textile candidate diagnostic in `experiments/corpus_material_candidate_reviews.json` rather than fixed-slot coverage):

| Case ID (Category) | Dimensions (`1x → 4x`) | Candidate | Locked Mismatches | Interior Texture | Oversharpen Restraint | Fabric Weave | Drift Verdict | Outcome |
| :--- | :---: | :--- | :---: | :---: | :---: | :---: | :---: | :--- |
| `wool_boucle` candidate (`cc0_polyhaven_wool_boucle_2k.jpg`, pre-`1e28ab8`) | `2048×2538 → 8192×10152` | `SwinIR-lightweight-DIV2K-x4` (`154` tiles) | `0` | Pass (`3.43×` var, `3.48×` midband) | Fail (`p95 5.71`, `frac 0.0987`, `3.39×` Nyq) | Pass (`0.946` ori, `1.000` FFT) | `WARN` (`1/81,408` blocks, `2.0 px`) | `FAIL_SHARPENING_ONLY` |
| `wool_boucle` candidate (`cc0_polyhaven_wool_boucle_2k.jpg`, pre-`1e28ab8`) | `2048×2538 → 8192×10152` | `RealeSR-general-v3` (`BSD-3-Clause`) | `0` | Pass (`3.92×` var, `4.15×` midband) | Fail (`p95 15.00`, `frac 0.2886`, `1.71×` Nyq) | Pass (`0.919` ori, `1.000` FFT) | `FAIL` (`37/81,408` blocks, `4.472 px`) | `FAIL_SHARPENING_ONLY` |
| `mac_two_way_brass_zip` (`macros`) | `1066×1600 → 4264×6400` | `SwinIR-lightweight-DIV2K-x4` (`54` tiles) | `0` | Pass (`1.00×`, base-preserved outside lock) | Fail raw `zip_teeth` (`p95 35.00`, `frac 0.2789`, `10.52×` Nyq) | N/A | `PASS` (`0/26,800` blocks, `0.0 px`) | `FAIL_SHARPENING_ONLY` |
| `mac_two_way_brass_zip` (`macros`) | `1066×1600 → 4264×6400` | `RealeSR-general-v3` (`BSD-3-Clause`) | `0` | Pass (`1.00×`, base-preserved outside lock) | Fail raw `zip_teeth` (`p95 19.98`, `frac 0.1640`, `7.86×` Nyq) | N/A | `PASS` (`0/26,800` blocks, `0.0 px`) | `FAIL_SHARPENING_ONLY` |

Key findings:

1. **Both models still fail raw oversharpening restraint on `wool_boucle` and `mac_two_way_brass_zip`**: While `SwinIR-lightweight-DIV2K-x4` reduced `wool_boucle` contour overshoot by ~2.6× (`p95 5.71` vs `15.00`, `0.0987` vs `0.2886` overshoot fraction) and reduced flagged drift blocks (`1` `WARN` at `2.0 px` vs `37` `FAIL` at `4.472 px`), it still exceeded the `0.05` overshoot fraction limit. On `mac_two_way_brass_zip`, both unmasked candidates exhibited severe raw-ROI overshoot on metallic zipper teeth (`19.98–35.00` p95 luma excursion), confirming the necessity of Studio's `must_lock_base` structural locks (`0` locked pixel mismatches in final guarded outputs).
2. **Model & training-data terms recorded (`config/model-provenance-v1.json`)**: `swinir-lightweight-div2k-x4` is pinned (`09fad24e32ae62722e1a055efde9921328f4137981bab0a42a4a3a806306c58e`) with `commercial_status: "unclear_terms_review_required"` and `production_terms_cleared: false`. The SwinIR repository declares `Apache-2.0` (`https://github.com/JingyunLiang/SwinIR/blob/main/LICENSE`), and the official DIV2K page (`https://data.vision.ee.ethz.ch/cvl/DIV2K/`, License section) limits DIV2K dataset access to academic research. Neither cited primary source explicitly states that the released `002_lightweightSR_DIV2K_s64w8_SwinIR-S_x4.pth` checkpoint is itself non-commercial or that deploying it necessarily requires retraining; checkpoint/data obligations remain unresolved, and the checkpoint stays excluded from commercial shipping until resolved.
3. **No promotion or held-out signoff**: `acceptance_status` remains `blocked_incomplete_evidence`. Off-repo receipts and crops are stored under `/Users/tyf12/melato-corpus/fidelis/release-evidence/calibration-multicase/{realesr-zip,realesr-tweed,swinir-zip,swinir-tweed}/`.
