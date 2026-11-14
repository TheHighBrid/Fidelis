import runpy
from pathlib import Path
import unittest

import numpy as np

compose_product = runpy.run_path(
    str(Path(__file__).resolve().parents[1] / "scripts/product-upscale.py")
)["compose_product"]


class ProductUpscaleTests(unittest.TestCase):
    def test_edge_stays_exact_with_feather_and_candidate_detail(self):
        base = np.full((64, 64, 3), 20, dtype=np.uint8)
        base[:, 32:] = 150
        candidate = np.minimum(base.astype(np.uint16) + 40, 255).astype(np.uint8)
        result, locked = compose_product(base, candidate, [])
        self.assertTrue(locked[32, 32])
        np.testing.assert_array_equal(result[locked], base[locked])
        np.testing.assert_array_equal(result[:, :8], candidate[:, :8])
        self.assertGreater(result[32, 24, 0], base[32, 24, 0])
        self.assertLess(result[32, 24, 0], candidate[32, 24, 0])

    def test_explicit_lock_wins_over_unlock(self):
        base = np.zeros((64, 64, 3), dtype=np.uint8)
        base[:, 32:] = 120
        candidate = np.full_like(base, 200)
        rois = [
            {"id": "allow", "kind": "fabric", "policy": "texture_allowed",
             "override": "unlock", "rect": [20, 0, 24, 64]},
            {"id": "zipper", "kind": "hardware", "policy": "preserve",
             "override": "lock", "rect": [30, 28, 4, 8]},
        ]
        result, locked = compose_product(base, candidate, rois)
        self.assertFalse(locked[5, 32])
        self.assertTrue(locked[32, 32])
        np.testing.assert_array_equal(result[32, 32], base[32, 32])
        np.testing.assert_array_equal(result[5, 32], candidate[5, 32])


if __name__ == "__main__":
    unittest.main()
