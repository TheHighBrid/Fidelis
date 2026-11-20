"""Boundary and attenuation contracts for F09 semantic routing.

These fixtures exercise only deterministic routing, not segmentation accuracy.
"""
import unittest

import numpy as np

from fidelis.studio.confidence_routing import CLASSES, route_confidence_masks


class ConfidenceRoutingBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.probs = {
            "skin": np.array([[0.80, 0.80, 0.90, 0.90, 0.90]], dtype=np.float64),
            "hair": np.array([[0.65, 0.66, 0.75, 0.10, 0.10]], dtype=np.float64),
            "fabric": np.array([[0.05, 0.05, 0.10, 0.10, 0.10]], dtype=np.float64),
        }
        self.protect = np.array([[0., 0., 0., 1., 0.]], dtype=np.float64)

    def test_threshold_margin_and_full_lock_boundaries(self):
        result = route_confidence_masks(self.probs, protect=self.protect)
        self.assertAlmostEqual(float(result["skin"][0, 0]), 0.8, places=6)
        self.assertEqual(result["skin"][0, 1], 0)  # gap below 0.15
        self.assertAlmostEqual(float(result["skin"][0, 2]), 0.9, places=6)
        self.assertEqual(result["skin"][0, 3], 0)  # explicit lock wins
        self.assertAlmostEqual(float(result["skin"][0, 4]), 0.9, places=6)
        for name in ("hair", "fabric"):
            self.assertTrue(np.all(result[name] == 0))

    def test_zero_certainty_leaves_base_and_preserves_protection(self):
        result = route_confidence_masks(
            self.probs,
            protect=self.protect,
            confidence=np.zeros_like(self.protect),
        )
        for name in CLASSES:
            self.assertTrue(np.all(result[name] == 0))
        np.testing.assert_array_equal(result["protect"], self.protect.astype(np.float32))

    def test_confidence_attenuation_is_monotone_and_never_weakens_lock(self):
        low = route_confidence_masks(
            self.probs, protect=self.protect,
            confidence=np.full_like(self.protect, 0.2),
        )
        high = route_confidence_masks(
            self.probs, protect=self.protect,
            confidence=np.full_like(self.protect, 0.8),
        )
        for name in CLASSES:
            self.assertTrue(np.all(low[name] <= high[name]))
            self.assertTrue(np.all(high[name][self.protect == 1] == 0))
        np.testing.assert_array_equal(low["protect"], high["protect"])

    def test_invalid_threshold_and_margin_rejected(self):
        for kwargs in (
            {"threshold": 0}, {"threshold": 1.01}, {"threshold": np.nan},
            {"margin": -0.01}, {"margin": 1.01}, {"margin": np.inf},
        ):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    route_confidence_masks(self.probs, protect=self.protect, **kwargs)


if __name__ == "__main__":
    unittest.main()
