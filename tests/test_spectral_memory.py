"""Native-grid and scratch-lifecycle checks for bounded spectral reduction."""
import tempfile
from pathlib import Path
import unittest
from unittest import mock

import numpy as np

from fidelis.eval import spectral_memory
from fidelis.eval.spectral_memory import spectral_band_means
from fidelis.eval.texture_metrics import _fft_power_spectrum, _radial_frequency_grid


BANDS = {"mid": (0.06, 0.25, True), "nyq": (0.25, 0.5, False)}


def reference_means(signal, bands=BANDS):
    power = _fft_power_spectrum(signal)
    radius = _radial_frequency_grid(*signal.shape)
    result = {}
    for name, (low, high, inclusive_low) in bands.items():
        mask = ((radius >= low) if inclusive_low else (radius > low)) & (radius <= high)
        result[name] = float(np.mean(power[mask])) if np.any(mask) else 0.0
    return result


class SpectralMemoryTests(unittest.TestCase):
    def assertReference(self, signal, bands=BANDS, block_size=3):
        expected = reference_means(signal, bands)
        with tempfile.TemporaryDirectory() as directory:
            actual = spectral_band_means(signal, bands, directory, block_size)
            self.assertEqual(list(Path(directory).iterdir()), [])
        self.assertEqual(actual.keys(), expected.keys())
        for name in expected:
            # NumPy 2's full-image complex64 power mean accumulates float32;
            # the bounded reduction changes that summation order, not its bins.
            np.testing.assert_allclose(actual[name], expected[name], rtol=4e-7, atol=1e-18)
        return actual, expected

    def test_random_odd_even_rectangles_and_degenerate_axes(self):
        rng = np.random.default_rng(129)
        for shape in ((17, 22), (18, 23), (19, 21), (20, 24), (1, 13), (14, 1), (1, 1)):
            for block_size in (1, 7, 128):
                with self.subTest(shape=shape, block_size=block_size):
                    self.assertReference(rng.normal(size=shape).astype(np.float32), block_size=block_size)

    def test_zero_and_constant_signals(self):
        for shape in ((15, 18), (16, 19), (1, 1)):
            for value in (0.0, 17.0):
                with self.subTest(shape=shape, value=value):
                    self.assertReference(np.full(shape, value, dtype=np.float32))

    def test_boundary_frequencies_and_empty_bands(self):
        # Native bins exactly on .06, .25 and .5 distinguish inclusivity.
        x = np.arange(100)
        signal = np.broadcast_to(
            sum(np.cos(2 * np.pi * frequency * x) for frequency in (0.06, 0.25, 0.5)),
            (20, 100),
        ).astype(np.float32)
        bands = dict(BANDS, zero=(0, 0, True),
                     at_low=(0.06, 0.06, True), empty_low=(0.06, 0.06, False),
                     at_quarter=(0.25, 0.25, True), empty_quarter=(0.25, 0.25, False),
                     at_half=(0.5, 0.5, True), empty_high=(1, 2, True))
        actual, _ = self.assertReference(signal, bands, block_size=13)
        for name in ("at_low", "at_quarter", "at_half"):
            self.assertGreater(actual[name], 0)
        for name in ("empty_low", "empty_quarter", "empty_high"):
            self.assertEqual(actual[name], 0)

    def test_same_ratio_threshold_decisions(self):
        rng = np.random.default_rng(51)
        base = rng.normal(size=(73, 82)).astype(np.float32)
        base_actual, base_expected = self.assertReference(base, block_size=11)
        for gain in (0.8, 1.0, 1.1, 1.4):
            actual, expected = self.assertReference(base * np.float32(gain), block_size=11)
            actual_ratio = actual["mid"] / max(base_actual["mid"], 1e-9)
            expected_ratio = expected["mid"] / max(base_expected["mid"], 1e-9)
            self.assertEqual(actual_ratio >= 1.0, expected_ratio >= 1.0)
            actual_nyq = actual["nyq"] / max(actual["mid"], 1e-9)
            expected_nyq = expected["nyq"] / max(expected["mid"], 1e-9)
            self.assertEqual(actual_nyq <= 1.2, expected_nyq <= 1.2)

    def test_only_strip_mappings_and_one_axis_ffts(self):
        signal = np.arange(43 * 67, dtype=np.float32).reshape(43, 67)
        real_memmap, real_fft = np.memmap, np.fft.fft
        mapped_shapes, fft_shapes = [], []

        def map_strip(*args, **kwargs):
            mapped_shapes.append(kwargs["shape"])
            return real_memmap(*args, **kwargs)

        def fft_strip(array, *args, **kwargs):
            fft_shapes.append(array.shape)
            return real_fft(array, *args, **kwargs)

        with mock.patch.object(np, "memmap", side_effect=map_strip), \
                mock.patch.object(np.fft, "fft", side_effect=fft_strip), \
                mock.patch.object(np.fft, "fft2", side_effect=AssertionError("full FFT")), \
                mock.patch.object(np.fft, "fftshift", side_effect=AssertionError("full shift")):
            spectral_band_means(signal, BANDS, block_size=5)
        self.assertTrue(mapped_shapes)
        self.assertTrue(all(rows <= 5 and width == 67 for rows, width in mapped_shapes))
        self.assertTrue(all(len(shape) == 1 or min(shape) <= 5 for shape in fft_shapes))

    def test_scratch_cleanup_when_column_fft_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(spectral_memory, "_column_transform", side_effect=OSError("scratch read failed")):
                with self.assertRaisesRegex(OSError, "scratch read failed"):
                    spectral_band_means(np.ones((13, 17), np.float32), BANDS, directory, 4)
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_scratch_cleanup_when_row_fft_fails(self):
        real_fft = np.fft.fft

        def fail_row(array, *args, **kwargs):
            if array.ndim == 2:
                raise OSError("row transform failed")
            return real_fft(array, *args, **kwargs)

        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(np.fft, "fft", side_effect=fail_row):
                with self.assertRaisesRegex(OSError, "row transform failed"):
                    spectral_band_means(np.ones((13, 17), np.float32), BANDS, directory, 4)
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_scratch_cleanup_and_mapping_close_when_flush_fails(self):
        real_memmap = np.memmap
        mapped = []

        def map_strip(*args, **kwargs):
            rows = real_memmap(*args, **kwargs)
            mapped.append(rows)
            return rows

        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(np, "memmap", side_effect=map_strip), \
                    mock.patch.object(real_memmap, "flush", side_effect=OSError("scratch full")):
                with self.assertRaisesRegex(OSError, "scratch full"):
                    spectral_band_means(np.ones((13, 17), np.float32), BANDS, directory, 4)
            self.assertEqual(list(Path(directory).iterdir()), [])
        self.assertTrue(mapped)
        self.assertTrue(all(rows._mmap.closed for rows in mapped))

    def test_scratch_failure_is_explicit(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "missing"
            with self.assertRaises(FileNotFoundError):
                spectral_band_means(np.ones((4, 5), np.float32), BANDS, missing)
            self.assertFalse(missing.exists())

    def test_input_validation_and_no_requested_bands(self):
        with self.assertRaises(TypeError):
            spectral_band_means(np.ones((4, 5), np.float64), BANDS)
        for signal in (np.ones(5, np.float32), np.ones((0, 5), np.float32)):
            with self.assertRaises(ValueError):
                spectral_band_means(signal, BANDS)
        for size in (0, -1):
            with self.assertRaises(ValueError):
                spectral_band_means(np.ones((4, 5), np.float32), BANDS, block_size=size)
        with self.assertRaises(TypeError):
            spectral_band_means(np.ones((4, 5), np.float32), BANDS, block_size=1.5)
        for bounds in ((-1, 1, True), (1, 0, True), (0, np.inf, True)):
            with self.assertRaises(ValueError):
                spectral_band_means(np.ones((4, 5), np.float32), {"bad": bounds})
        self.assertEqual(spectral_band_means(np.ones((4, 5), np.float32), {}), {})


if __name__ == "__main__":
    unittest.main()
