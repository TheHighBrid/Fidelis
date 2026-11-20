"""Fail-closed structural ROI screening and stripe invariance."""
import unittest

import numpy as np

from fidelis.studio.structure import measure_region


class StructuralScreenContractTests(unittest.TestCase):
    def test_stripe_size_does_not_change_edge_or_pixel_counts(self):
        base = np.zeros((9, 7, 3), dtype=np.uint8)
        base[3:, :, :] = 210
        base[:, 4:, 0] = 110
        candidate = base.copy()
        candidate[4:, :, :] = 30
        candidate[:, 5:, 0] = 200
        expected = measure_region(base, candidate, [1, 1, 6, 8], 8)
        self.assertGreater(expected["strong_edge_disagreements"], 0)
        for rows in (1, 2, 3, 4, 7, 9, 32):
            with self.subTest(rows=rows):
                self.assertEqual(measure_region(base, candidate, [1, 1, 6, 8], rows), expected)

    def test_identical_roi_is_unchanged(self):
        base = np.arange(6 * 8 * 3, dtype=np.uint8).reshape(6, 8, 3)
        result = measure_region(base, base.copy(), [2, 1, 4, 4], 1)
        self.assertEqual(result["changed_pixels"], 0)
        self.assertEqual(result["strong_edge_disagreements"], 0)

    def test_invalid_stripes_fail_closed(self):
        base = np.zeros((3, 4, 3), dtype=np.uint8)
        for rows in (0, -1, 1.5, True, "2", None):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                measure_region(base, base, [0, 0, 4, 3], rows)

    def test_invalid_grids_fail_closed(self):
        base = np.zeros((3, 4, 3), dtype=np.uint8)
        bad = (np.zeros((4, 4, 3), dtype=np.uint8),
               np.zeros((3, 4, 4), dtype=np.uint8),
               np.zeros((3, 4), dtype=np.uint8),
               np.zeros((3, 4, 3), dtype=np.float32))
        for candidate in bad:
            with self.subTest(shape=candidate.shape, dtype=str(candidate.dtype)):
                with self.assertRaises(ValueError):
                    measure_region(base, candidate, [0, 0, 4, 3], 2)

    def test_out_of_grid_rectangle_fails_closed(self):
        base = np.zeros((3, 4, 3), dtype=np.uint8)
        for region in ([3, 0, 2, 2], [-1, 0, 1, 1], [0, 0, 0, 1],
                       [0, 2, 1, 2], [0, 0, True, 1]):
            with self.subTest(region=region), self.assertRaises(ValueError):
                measure_region(base, base, region, 2)


if __name__ == "__main__":
    unittest.main()
