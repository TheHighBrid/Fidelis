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
Next: compare on the declared velvet calibration subject before considering any
model/preset promotion; preserve the previous failing RealeSR comparisons.
