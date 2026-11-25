"""Native-grid spectral band means without full-image FFT working arrays."""
from __future__ import annotations

import operator
import tempfile
from collections.abc import Mapping
from contextlib import contextmanager
from pathlib import Path

import numpy as np


@contextmanager
def _mapped_rows(path, dtype, width, start, stop, *, mode="r"):
    """Map only a row block, then release its resident pages before proceeding."""
    rows = np.memmap(
        path, dtype=dtype, mode=mode,
        offset=start * width * dtype.itemsize, shape=(stop - start, width),
    )
    try:
        yield rows
    finally:
        # Explicit close is needed: dropping a whole-file memmap does not give a
        # useful peak-RSS bound while it is being traversed. No views escape here.
        rows._mmap.close()


def _write_row_transforms(signal, path, dtype, block_size):
    height, width = signal.shape
    wy, wx = np.hanning(height), np.hanning(width)
    for start in range(0, height, block_size):
        stop = min(start + block_size, height)
        # Match outer(float64 Hann, float64 Hann).astype(float32), then the
        # float32 signal multiplication. Casting the 1D Hann vectors first would
        # change the original window's rounding.
        window = (wy[start:stop, None] * wx[None, :]).astype(np.float32)
        windowed = signal[start:stop] * window
        transformed = np.fft.fft(windowed, axis=1)
        with _mapped_rows(path, dtype, width, start, stop, mode="r+") as rows:
            rows[:] = transformed
            rows.flush()


def _column_transform(path, dtype, shape, start, stop, block_size):
    height, width = shape
    columns = np.empty((height, stop - start), dtype=dtype)
    for row_start in range(0, height, block_size):
        row_stop = min(row_start + block_size, height)
        with _mapped_rows(path, dtype, width, row_start, row_stop) as rows:
            columns[row_start:row_stop] = rows[:, start:stop]
    # fft2's default axis order is last axis first, then the penultimate axis.
    return np.fft.fft(columns, axis=0)


def _validated_bands(bands):
    normalized = {}
    for name, (low, high, inclusive_low) in bands.items():
        if not np.isfinite(low) or not np.isfinite(high) or low < 0 or high < low:
            raise ValueError("spectral bands require finite 0 <= low <= high")
        normalized[name] = (low, high, inclusive_low)
    return normalized


def spectral_band_means(
    signal: np.ndarray,
    bands: Mapping[str, tuple[float, float, bool]],
    scratch_dir: str | Path | None = None,
    block_size: int = 128,
) -> dict[str, float]:
    """Return mean native-grid Hann-windowed power in each radial band.

    ``bands`` maps names to ``(low, high, inclusive_low)`` in cycles/pixel; the
    upper boundary is always inclusive. Empty bands have mean zero. The window,
    signal multiplication and FFT axis order match ``np.fft.fft2`` on the full
    float32 windowed signal, including the installed NumPy FFT precision. No
    crop, downsampling, padding or change to frequency boundaries is performed.

    Working arrays and resident file mappings are bounded by strips of at most
    ``block_size`` rows/columns, plus one-dimensional frequency/window vectors.
    The caller's input remains resident. A temporary backing file needs
    ``height * width * FFT-complex-itemsize`` bytes, with filesystem/cache and
    NumPy FFT workspace overhead additional. Scratch I/O errors propagate; files
    and mappings are removed on both success and exceptions. This does not bound
    total application RSS or other metrics' allocations.

    Band sums use float64 accumulation across strips. Consequently the reduction
    order differs from a full-image shifted/boolean-selected NumPy mean; tiny
    floating point differences are possible, particularly with complex64 FFTs.
    """
    if signal.ndim != 2 or min(signal.shape) <= 0:
        raise ValueError("signal must be a nonempty two-dimensional array")
    if signal.dtype != np.float32:
        raise TypeError("signal must have float32 dtype")
    block_size = operator.index(block_size)
    if block_size <= 0:
        raise ValueError("block_size must be positive")
    bands = _validated_bands(bands)
    if not bands:
        return {}

    height, width = signal.shape
    # NumPy 1.x promotes float32 FFTs to complex128, whereas NumPy 2.x can
    # preserve complex64. Infer this without transforming the entire image.
    dtype = np.fft.fft(np.zeros(1, dtype=np.float32)).dtype
    fy = np.fft.fftfreq(height)
    fx = np.fft.fftfreq(width)
    sums = {name: 0.0 for name in bands}
    counts = {name: 0 for name in bands}
    with tempfile.TemporaryDirectory(prefix="fidelis-spectrum-", dir=scratch_dir) as temp:
        path = Path(temp) / "row-transforms.dat"
        with path.open("wb") as backing:
            backing.truncate(height * width * dtype.itemsize)
        _write_row_transforms(signal, path, dtype, block_size)
        for start in range(0, width, block_size):
            stop = min(start + block_size, width)
            spectrum = _column_transform(path, dtype, signal.shape, start, stop, block_size)
            power = (np.abs(spectrum) ** 2) / max(float(height * width), 1.0)
            # fftshift permutes bins only. Apply the same radial coordinates in
            # unshifted order to avoid allocating a shifted complex-image copy.
            radius = np.sqrt(fy[:, None] ** 2 + fx[None, start:stop] ** 2)
            for name, (low, high, inclusive_low) in bands.items():
                mask = ((radius >= low) if inclusive_low else (radius > low)) & (radius <= high)
                sums[name] += float(np.sum(power, where=mask, dtype=np.float64))
                counts[name] += int(np.count_nonzero(mask))
    return {name: sums[name] / counts[name] if counts[name] else 0.0 for name in bands}


def _weave_power_file(signal, complex_path, power_path, dtype, block_size):
    """Store shifted C-order power on disk, matching reference reduction order."""
    height, width = signal.shape
    real_dtype = np.empty(1, dtype=dtype).real.dtype
    transposed_path = power_path.with_suffix(".transposed.dat")
    with complex_path.open("wb") as backing:
        backing.truncate(height * width * dtype.itemsize)
    with transposed_path.open("wb") as backing:
        backing.truncate(height * width * real_dtype.itemsize)
    _write_row_transforms(signal, complex_path, dtype, block_size)
    # Integer unshifted bin coordinates reproduce shifted pixel-radius >= 2.
    iy = np.arange(height, dtype=np.int64)
    ix = np.arange(width, dtype=np.int64)
    iy = np.where(iy < (height + 1) // 2, iy, iy - height)
    ix = np.where(ix < (width + 1) // 2, ix, ix - width)
    for start in range(0, width, block_size):
        stop = min(start + block_size, width)
        spectrum = _column_transform(complex_path, dtype, signal.shape, start, stop, block_size)
        power = (np.abs(spectrum) ** 2) / max(float(height * width), 1.0)
        mask = iy[:, None] ** 2 + ix[None, start:stop] ** 2 >= 4
        np.multiply(power, mask, out=power)
        with _mapped_rows(transposed_path, real_dtype, height, start, stop, mode="r+") as rows:
            rows[:] = power.T
            rows.flush()
    complex_path.unlink()
    # Transpose/shift once into reference C order. Flushing every FFT column's
    # scatter into every output row block would add quadratic synchronous I/O.
    with power_path.open("wb") as backing:
        backing.truncate(height * width * real_dtype.itemsize)
    for row_start in range(0, height, block_size):
        row_stop = min(row_start + block_size, height)
        source_rows = (np.arange(row_start, row_stop) - height // 2) % height
        with _mapped_rows(power_path, real_dtype, width, row_start, row_stop, mode="r+") as rows:
            for start in range(0, width, block_size):
                stop = min(start + block_size, width)
                columns = (np.arange(start, stop) + width // 2) % width
                with _mapped_rows(transposed_path, real_dtype, height, start, stop) as source:
                    rows[:, columns] = source[:, source_rows].T
            rows.flush()
    transposed_path.unlink()
    with _mapped_rows(power_path, real_dtype, width, 0, height) as frame:
        return float(np.sum(frame))


def _normalize_power_file(path, dtype, shape, total, block_size):
    height, width = shape
    for start in range(0, height, block_size):
        stop = min(start + block_size, height)
        with _mapped_rows(path, dtype, width, start, stop, mode="r+") as rows:
            np.divide(rows, total + 1e-12, out=rows)
            rows.flush()
    # Preserve the actual NumPy/BLAS reduction and input order. Replacing this
    # with float64 strip sums changes large float32 norms measurably.
    with _mapped_rows(path, dtype, width, 0, height) as frame:
        return np.linalg.norm(frame)


def spectral_weave_coherence(
    ref_signal: np.ndarray,
    cand_signal: np.ndarray,
    scratch_dir: str | Path | None = None,
    block_size: int = 128,
) -> tuple[float, float]:
    """Compare full-ROI Hann spectra using bounded mappings and unchanged floors.

    Inputs are already mean-centered by the caller. FFT precision/order,
    pixel-bin radius >= 2 exclusion, spectral
    normalization and denominator floors follow the material metric reference.
    No crop, padding or resampling occurs. Power is stored in shifted C order so
    NumPy sums and BLAS norms retain the reference ordering and precision. FFT
    and elementwise working arrays use strips; scalar reductions map one whole
    real disk frame, whose resident pages can grow to a frame before unmapping.
    Inputs stay resident; scratch peak is two real power frames plus one complex
    frame (or three real frames for the cross product). Other application buffers
    and filesystem cache are additional. This is not a total-process RSS bound.
    """
    reference, candidate = ref_signal, cand_signal
    if reference.ndim != 2 or candidate.ndim != 2 or reference.shape != candidate.shape:
        raise ValueError("weave inputs must be aligned two-dimensional arrays")
    if min(reference.shape) <= 0:
        raise ValueError("weave inputs must be nonempty")
    if reference.dtype != np.float32 or candidate.dtype != np.float32:
        raise TypeError("weave inputs must have float32 dtype")
    block_size = operator.index(block_size)
    if block_size <= 0:
        raise ValueError("block_size must be positive")
    height, width = reference.shape
    from fidelis.eval.texture_metrics import _fft_power_spectrum
    probe_power = _fft_power_spectrum(np.zeros((3, 5), dtype=np.float32))
    if not (probe_power * np.ones((3, 5), dtype=bool)).flags.c_contiguous:
        raise RuntimeError("reference weave power layout is not supported")
    dtype = np.fft.fft(np.zeros(1, dtype=np.float32)).dtype
    real_dtype = np.empty(1, dtype=dtype).real.dtype
    with tempfile.TemporaryDirectory(prefix="fidelis-weave-", dir=scratch_dir) as temp:
        root = Path(temp)
        ref_path, cand_path = root / "reference.dat", root / "candidate.dat"
        complex_path = root / "row-transforms.dat"
        sum_r = _weave_power_file(reference, complex_path, ref_path, dtype, block_size)
        sum_c = _weave_power_file(candidate, complex_path, cand_path, dtype, block_size)
        if sum_r < 1e-9 and sum_c < 1e-9:
            return 1.0, 1.0
        norm_r = _normalize_power_file(ref_path, real_dtype, reference.shape, sum_r, block_size)
        norm_c = _normalize_power_file(cand_path, real_dtype, reference.shape, sum_c, block_size)
        cross_path = root / "cross.dat"
        with cross_path.open("wb") as backing:
            backing.truncate(height * width * real_dtype.itemsize)
        for start in range(0, height, block_size):
            stop = min(start + block_size, height)
            with _mapped_rows(ref_path, real_dtype, width, start, stop) as ref:
                with _mapped_rows(cand_path, real_dtype, width, start, stop) as cand:
                    with _mapped_rows(cross_path, real_dtype, width, start, stop, mode="r+") as cross_rows:
                        np.multiply(ref, cand, out=cross_rows)
                        cross_rows.flush()
        with _mapped_rows(cross_path, real_dtype, width, 0, height) as frame:
            cross = np.sum(frame)
        denominator = float(norm_r * norm_c)
        return float(cross / max(denominator, 1e-12)), sum_c / max(sum_r, 1e-9)
