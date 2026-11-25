"""Compatibility with the native-grid metric definitions retained at 83f739a."""

import unittest
from unittest.mock import patch

import cv2
import numpy as np

from fidelis.eval import texture_metrics as metrics


class TextureMemoryTests(unittest.TestCase):
    def test_chunked_luminance_is_bit_exact_for_strided_and_float_inputs(self):
        rng = np.random.default_rng(42)
        source = rng.integers(0, 256, (293, 371, 3), dtype=np.uint8)
        for image in (source, source[:, ::2], source.astype(np.float64) / 3):
            old = image.astype(np.float32)
            expected = 0.2126 * old[:, :, 0] + 0.7152 * old[:, :, 1] + 0.0722 * old[:, :, 2]
            np.testing.assert_array_equal(metrics._bt709_luminance(image), expected)

    def test_reduced_temporaries_retain_reference_metrics_and_decisions(self):
        rng = np.random.default_rng(42)
        candidate = rng.integers(0, 256, (133, 197, 3), dtype=np.uint8)
        baseline = cv2.GaussianBlur(candidate, (5, 5), 1.1)
        for threshold in (4_000_000, 0):
            with self.subTest(threshold=threshold), patch.object(metrics, "_SPECTRAL_MEMORY_THRESHOLD", threshold):
                texture = metrics.measure_interior_texture_retention(candidate, baseline)
                contour = metrics.measure_oversharpening_restraint(candidate, baseline)
                self.assertTrue(texture["passed"])
                self.assertFalse(contour["passed"])
                self.assertEqual(texture["interior_pixel_count"], 14411)
                self.assertEqual(contour["contour_pixel_count"], 17304)
                for key, value in {"interior_texture_variance_ratio": 27.001703,
                                   "interior_midband_energy_ratio": 6.882092}.items():
                    self.assertAlmostEqual(texture[key], value, places=5)
                for key, value in {"contour_overshoot_mean": 26.612518,
                                   "contour_overshoot_p95": 73.503578,
                                   "contour_nyquist_gain_vs_bicubic": 27.358342}.items():
                    # float32 spacing near 73.5 is ~7.6e-6 across OpenCV/NumPy builds (1 ULP).
                    places = 4 if key == "contour_overshoot_p95" else 5
                    self.assertAlmostEqual(contour[key], value, places=places)

    def test_exact_baseline_at_texture_threshold_stays_passing(self):
        rng = np.random.default_rng(7)
        image = rng.integers(0, 256, (91, 128, 3), dtype=np.uint8)
        with patch.object(metrics, "_SPECTRAL_MEMORY_THRESHOLD", 0):
            result = metrics.measure_interior_texture_retention(image, image)
        self.assertTrue(result["passed"])
        self.assertEqual(result["interior_texture_variance_ratio"], 1.0)
        self.assertEqual(result["interior_midband_energy_ratio"], 1.0)


if __name__ == "__main__":
    unittest.main()
