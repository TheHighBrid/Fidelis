"""Native-grid spectral band means without full-image FFT working arrays."""
from __future__ import annotations

from collections.abc import Mapping
from contextlib import contextmanager
import operator
from pathlib import Path
import tempfile

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
