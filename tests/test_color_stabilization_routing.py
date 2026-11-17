"""Regression tests for strict color stabilization routing and hybrid dtype."""
import unittest

import numpy as np

from fidelis.postprocess.color_fix import adain_color_fix, stabilize_colors, wavelet_color_fix


class ColorStabilizationRoutingTests(unittest.TestCase):
    def setUp(self):
        self.source = np.full((8, 8, 3), 100, dtype=np.uint8)
        self.reference = np.full((8, 8, 3), 110, dtype=np.uint8)

    def test_unknown_mode_rejected_instead_of_silent_noop(self):
        for mode in ("", "WAVELET", "none", "off"):
            with self.subTest(mode=mode), self.assertRaisesRegex(ValueError, "Unsupported color stabilization mode"):
                stabilize_colors(self.source, self.reference, preferred_mode=mode)

    def test_invalid_scale_rejected_in_all_modes(self):
        for scale in (0, -1, float("nan"), float("inf"), -float("inf")):
            for mode in ("auto", "wavelet", "adain", "hybrid"):
                with self.subTest(scale=scale, mode=mode), self.assertRaisesRegex(ValueError, "finite positive"):
                    stabilize_colors(self.source, self.reference, scale_factor=scale, preferred_mode=mode)

    def test_hybrid_float_preserves_float_range_and_dtype(self):
        sr = np.linspace(0.1, 0.9, num=8 * 8 * 3, dtype=np.float32).reshape(8, 8, 3)
        ref = np.flip(sr, axis=0).copy()
        actual = stabilize_colors(sr, ref, preferred_mode="hybrid")
        expected = (wavelet_color_fix(sr, ref) + adain_color_fix(sr, ref)) / 2
        self.assertEqual(actual.dtype, np.float32)
        np.testing.assert_allclose(actual, expected, atol=1e-6)
        self.assertGreaterEqual(actual.min(), 0)
        self.assertLessEqual(actual.max(), 1)

    def test_hybrid_uint8_rounds_instead_of_truncating(self):
        sr = np.arange(8 * 8 * 3, dtype=np.uint8).reshape(8, 8, 3)
        ref = np.flip(sr, axis=1).copy()
        actual = stabilize_colors(sr, ref, preferred_mode="hybrid")
        expected = np.rint((wavelet_color_fix(sr, ref).astype(np.float32) +
                            adain_color_fix(sr, ref).astype(np.float32)) / 2).astype(np.uint8)
        self.assertEqual(actual.dtype, np.uint8)
        np.testing.assert_array_equal(actual, expected)


if __name__ == "__main__":
    unittest.main()
