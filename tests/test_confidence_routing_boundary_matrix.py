"""Additional F09 boundary fixtures for explicit unknown and protection behavior."""
import unittest

import numpy as np

from fidelis.studio.confidence_routing import route_confidence_masks


class ConfidenceRoutingBoundaryMatrixTests(unittest.TestCase):
    def test_threshold_nextafter_below_is_not_accepted(self):
        below = np.nextafter(np.float64(0.8), np.float64(0))
        probabilities = {
            "skin": np.array([[below, 0.8]], dtype=np.float64),
            "hair": np.zeros((1, 2), dtype=np.float64),
            "fabric": np.zeros((1, 2), dtype=np.float64),
        }
        routed = route_confidence_masks(probabilities, protect=np.zeros((1, 2)))
        self.assertEqual(routed["skin"][0, 0], 0)
        self.assertGreater(routed["skin"][0, 1], 0)

    def test_margin_nextafter_below_is_not_accepted(self):
        below = np.nextafter(np.float64(0.15), np.float64(0))
        probabilities = {
            "skin": np.array([[1.0, 1.0]]),
            "hair": np.array([[1.0 - below, 0.80]]),
            "fabric": np.zeros((1, 2)),
        }
        routed = route_confidence_masks(probabilities, protect=np.zeros((1, 2)), margin=0.15)
        self.assertEqual(routed["skin"][0, 0], 0)
        self.assertGreater(routed["skin"][0, 1], 0)

    def test_full_lock_never_receives_texture_across_classes(self):
        probabilities = {
            "skin": np.array([[0.99, 0.01, 0.01]]),
            "hair": np.array([[0.01, 0.99, 0.01]]),
            "fabric": np.array([[0.01, 0.01, 0.99]]),
        }
        routed = route_confidence_masks(probabilities, protect=np.ones((1, 3)))
        for label in ("skin", "hair", "fabric"):
            np.testing.assert_array_equal(routed[label], np.zeros((1, 3), dtype=np.float32))
        np.testing.assert_array_equal(routed["protect"], np.ones((1, 3), dtype=np.float32))

    def test_confidence_zero_preserves_protection_map(self):
        probabilities = {label: np.full((2, 3), 0.01) for label in ("skin", "hair", "fabric")}
        probabilities["fabric"][:] = 0.99
        lock = np.array([[0, 0.25, 1], [0.5, 0.75, 1]], dtype=np.float64)
        routed = route_confidence_masks(probabilities, protect=lock, confidence=np.zeros((2, 3)))
        np.testing.assert_array_equal(routed["protect"], lock.astype(np.float32))
        for label in ("skin", "hair", "fabric"):
            np.testing.assert_array_equal(routed[label], np.zeros((2, 3), dtype=np.float32))


if __name__ == "__main__":
    unittest.main()
