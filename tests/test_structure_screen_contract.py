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


    def test_changes_outside_roi_are_not_counted(self):
        base = np.zeros((8, 9, 3), dtype=np.uint8)
        candidate = base.copy()
        candidate[:, :3] = 255
        candidate[6:, :] = 255
        for rows in (1, 2, 5, 100):
            with self.subTest(rows=rows):
                result = measure_region(base, candidate, [3, 0, 6, 6], rows)
                self.assertEqual(result["pixels"], 36)
                self.assertEqual(result["changed_pixels"], 0)
                self.assertEqual(result["strong_edge_disagreements"], 0)

    def test_stripes_match_independent_full_roi_oracle(self):
        rng = np.random.default_rng(20261120)
        for height, width in ((1, 1), (2, 7), (7, 2), (11, 13)):
            base = rng.integers(0, 256, (height + 2, width + 2, 3), dtype=np.uint8)
            candidate = rng.integers(0, 256, base.shape, dtype=np.uint8)
            region = [1, 1, width, height]
            a = base[1:1 + height, 1:1 + width].astype(np.int32)
            b = candidate[1:1 + height, 1:1 + width].astype(np.int32)
            expected_pixels = int(np.count_nonzero(np.any(a != b, axis=2)))
            def luma(rgb):
                return (77 * rgb[..., 0] + 150 * rgb[..., 1] + 29 * rgb[..., 2]) >> 8
            la, lb = luma(a), luma(b)
            expected_edges = 0
            for axis in (0, 1):
                da, db = np.diff(la, axis=axis), np.diff(lb, axis=axis)
                ea = np.sign(da) * (np.abs(da) >= 24)
                eb = np.sign(db) * (np.abs(db) >= 24)
                expected_edges += int(np.count_nonzero(ea != eb))
            for rows in (1, 2, 3, height, height + 10):
                with self.subTest(grid=(height, width), rows=rows):
                    result = measure_region(base, candidate, region, rows)
                    self.assertEqual(result["changed_pixels"], expected_pixels)
                    self.assertEqual(result["strong_edge_disagreements"], expected_edges)


if __name__ == "__main__":
    unittest.main()
