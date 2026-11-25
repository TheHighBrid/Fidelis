# Native-grid evaluation memory checkpoint · #129

Base: `83f739a`; branch `work/f13-bounded-spectrum`. This is partial resource
remediation, not model certification or a passed full-resolution twill audition.

The interrupted `4351×2854` twill attempt still has no quality result. Its exact
4× target is `17404×11416` (`198,684,064` pixels). Bounded inference tiles did
not bound full-image evaluation arrays; no measured out-of-memory failure was
claimed and no input was silently reduced.

## Change and fixed criteria

Luminance conversion now uses row strips with bit-identical float32 arithmetic.
F2/F3 evaluate candidate and baseline high-pass signals sequentially and reuse
private buffers. Spectra above four million pixels use a temporary disk-backed
separable FFT, mapping bounded row/column strips. Scratch errors propagate and
temporary files are removed after success or exceptions.

Native dimensions, full-image Hann window, FFT precision/axis order, ROI masks,
frequency bands (`0.06 <= r <= 0.25`; `0.25 < r <= 0.50`) and pass thresholds
are unchanged. There is no crop, resampling, padding, or replacement patch metric.
Stripwise float64 band accumulation changes summation order relative to the
reference float32 mean: numerical agreement is close rather than bit-identical.
The measured maximum relative band-mean difference below was about `2.8e-8`;
exercised threshold decisions agree. Values arbitrarily close to a threshold
retain floating-point sensitivity. These metrics alone cannot provide creative
or release approval.

## Actual Apple M1 measurements

Host: 8 GiB Apple M1, macOS arm64, Python 3.12.16, NumPy 2.5.5. Each synthetic
method ran once in a separate child process at `2048×3072`, using identical input
bytes. macOS `ru_maxrss` below includes interpreter/import/input memory. These
are operation microbenchmarks, not full-application peak memory or model quality.

| Operation | Reference peak RSS | Revised peak RSS | Reference / revised time |
| --- | ---: | ---: | ---: |
| Luminance | 212,959,232 bytes | 124,518,400 bytes | 0.02433 / 0.01815 s |
| Spectral band means | 484,360,192 bytes | 129,286,144 bytes | 0.24656 / 0.32833 s |

Luminance output hashes match exactly:
`9d13a0fae7c9e2d1543726f8433d8eb2da43291d174cb72cb5f2b784109fbe5d`.
The FFT backing file was `50,331,648` bytes at this input/complex64 precision.
Filesystem cache and FFT workspace remain additional costs. No timing confidence
interval or whole-workflow speedup is inferred from these single runs.

Re-evaluated retained **guarded final** zipper pixels at `4264×6400` through F2
and F3: `7.12699 s`, peak RSS `1,516,470,272` bytes. Both stored inputs have SHA
`83b886d73a5148f85450de7b760cd46287e76fa50b5d225751c193dcd5b5e2e8`:
they are identical after protection. Their texture ratios and Nyquist gain are
`1.0`, and excursion is zero. This demonstrates operation at the native grid;
it is **not** a new model comparison. The original raw SwinIR zipper audition
remains `FAIL_SHARPENING_ONLY`, with no model/preset promotion or human review.

Private evidence under
`/Users/tyf12/melato-corpus/fidelis/release-evidence/memory-audit/`:

- `spectral-2048x3072-20261125.json` and `benchmark_spectral_129.py`: input,
  source/driver hashes, runtime, measured results and reproduction.
- `luminance-2048x3072-20261125.json`: input recipe, timing/RSS and output hashes.
- `guarded-zipper-129.json` and `benchmark_guarded_zipper_129.py`: retained image
  hashes and native-grid F2/F3 resource probe.

## Verification and remaining work

Thirteen new numerical/resource-shape/cleanup tests, six existing detail tests,
eight audition tests, and 25 packaging/adversarial tests passed locally. Tests
cover odd/even rectangles, degenerate axes, window/band boundaries, exact-baseline
thresholds, strided/float input, and FFT/disk failures. CI explicitly runs the new
tests; archive auditing requires the helper and its regression tests.

The initial full-suite run exposed an existing environment-dependent test: its
unavailable-Spandrel assertion relied on Torch/Spandrel being absent. This host
now has both installed for real MPS inference, so it tried to deserialize the
test's fake checkpoint. The test now explicitly simulates missing imports for
that assertion; its separate mocked-inference assertions remain. Real installed
dependencies are retained, and no application error is suppressed.

Local Web UI server and static smoke suites passed. The final full-suite result
and required Linux/macOS CI evidence are recorded in the associated PR.

Issue #129 stays open. Full-frame material/orientation, drift, masks and
composition still allocate image-sized buffers. Inspect and bound their peak
working set, then measure the unchanged complete twill workflow on this M1.
Neither the full 198.7MP case nor overall 60-case acceptance is qualified here.
