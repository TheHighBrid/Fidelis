# Native-grid weave score precision · F13 / #129

Base: `d68bcf0`; branch `work/f13-weave-reference-precision`.

The low-memory path from #131 changed float32/BLAS reduction order by replacing
normalized power-frame sums/norms with float64 strip statistics. A measured
`2048×3072` input gave reference coherence `0.9950751066207886` versus
`0.9950470357729967`. This discrepancy can affect values close to the fixed
`0.75` acceptance boundary. No threshold is changed to accommodate it.

## Correction

The existing `spectral_weave_coherence` interface still accepts already-centered
float32 signals; the material caller centers exactly once. Native dimensions,
full-ROI Hann window, FFT precision/axis order, radius-in-pixels `>= 2` mask,
normalization and denominator floors remain unchanged.

FFT power is generated in strips, then transposed and shifted into disk-backed
C-order frames. The actual NumPy sum, BLAS norm, normalization dtype and final
scalar-division dtype match the retained reference. A small runtime probe rejects
an unsupported reference power layout rather than silently changing the metric.
The `0.75` coherence and `0.90` energy criteria remain fixed.

Elementwise/FFT working arrays use strips. Scalar reductions map one complete
real frame and unmap it afterward: resident pages can grow to a real frame.
This is not a constant total-RSS promise. Scratch peak is two real frames plus
one complex frame during FFT production, or three real frames later; input arrays,
filesystem cache and other application buffers are additional. Temporary files
and mappings are cleaned up on success and failure.

## Actual M1 probe

Python 3.12.16, NumPy 2.5.5, macOS arm64. Single separate-child-process runs with
identical hashed synthetic float32 inputs at `2048×3072`:

| Method | Coherence | Energy ratio | Peak RSS (bytes) | Time (s) |
| --- | ---: | ---: | ---: | ---: |
| Original `27d633c` reference | 0.9950751066207886 | 1.0102778383143292 | 637,206,528 | 0.407794 |
| Previous bounded `d68bcf0` | 0.9950470357729967 | 1.0102777862371803 | 262,815,744 | 1.234015 |
| Corrected bounded path | 0.9950751066207886 | 1.0102778383143292 | 258,736,128 | 2.657233 |

Both corrected outputs match the reference exactly in this probe, retaining a
lower measured memory footprint. The extra disk passes are slower than the
previous bounded path in this single run. No timing confidence interval or whole
application latency/memory qualification is inferred.

Private evidence:
`/Users/tyf12/melato-corpus/fidelis/release-evidence/memory-audit/`
contains `weave-precision-2048x3072-20261125.json` and
`benchmark_weave_precision.py`, recording input, baseline, previous/current source,
driver and runtime identities. These are engineering probes, not image-quality
scores, new inference, human reviews or release approval.

## Verification and remaining gate

Nine focused tests passed, including exact float32 agreement at `1024×1536`,
odd/even/thin/strided inputs, identity/zero-energy behavior, neighborhoods around
the unchanged `0.75`/`0.90` criteria, and FFT/transpose/read/flush cleanup failures.
Independent agent review found no actionable issues and additionally checked
70 precision/floor cases and 20 exact masked-power-grid cases. This establishes
agreement in the exercised environment, not universal cross-version bit equality.

CI explicitly runs the new tests and the archive audit requires them. The final
full-suite and required CI results are recorded in the associated PR. #129 stays
open until the unchanged full 198.7MP twill workflow is actually run and verified.
The 60-case image-quality, human-review, device and owner-approval gates remain
separate; no model or preset is promoted by this correction.
