"""Spatial safety invariants for F09 confidence routing (no segmentation model)."""
import unittest

import numpy as np

from fidelis.studio.confidence_routing import CLASSES, route_confidence_masks


class SpatialRoutingInvariantTests(unittest.TestCase):
    def test_mixed_grid_preserves_unknown_ties_and_explicit_protection(self):
        skin = np.array([[.95, .95, .20], [.05, .90, .90]], dtype=np.float64)
        hair = np.array([[.02, .02, .10], [.96, .90, .02]], dtype=np.float64)
        fabric = np.array([[.01, .01, .12], [.02, .01, .03]], dtype=np.float64)
        protect = np.array([[0., 1., 0.], [.5, 0., .25]], dtype=np.float64)
        result = route_confidence_masks(
            dict(skin=skin, hair=hair, fabric=fabric), protect=protect
        )
        self.assertEqual(result["skin"][0, 0], np.float32(.95))
        self.assertEqual(result["skin"][0, 1], 0)
        self.assertEqual(result["skin"][0, 2], 0)
        self.assertEqual(result["skin"][1, 1], 0)  # tied classes
        self.assertAlmostEqual(float(result["hair"][1, 0]), .48, places=6)
        self.assertAlmostEqual(float(result["skin"][1, 2]), .675, places=6)
        for name in CLASSES:
            self.assertEqual(result[name][0, 1], 0)
            self.assertEqual(result[name][0, 2], 0)
            self.assertEqual(result[name][1, 1], 0)

    def test_randomized_grid_never_routes_two_classes_or_exceeds_lock_budget(self):
        rng = np.random.default_rng(6209)
        shape = (17, 19)
        probs = {name: rng.random(shape) for name in CLASSES}
        protect = rng.random(shape)
        protect[::4, ::3] = 1.0
        confidence = rng.random(shape)
        result = route_confidence_masks(
            probs, protect=protect, confidence=confidence
        )
        active = np.stack([result[name] > 0 for name in CLASSES])
        self.assertTrue(np.all(active.sum(axis=0) <= 1))
        total = sum((result[name] for name in CLASSES))
        self.assertTrue(np.all(total <= 1 - result["protect"] + 1e-7))
        self.assertTrue(np.all(total[result["protect"] == 1] == 0))
        self.assertTrue(all(mask.dtype == np.float32 for mask in result.values()))

    def test_inputs_are_not_modified_and_outputs_do_not_alias_inputs(self):
        probabilities = {
            name: np.full((3, 4), value, dtype=np.float64)
            for name, value in (("skin", .95), ("hair", .02), ("fabric", .01))
        }
        protect = np.full((3, 4), .25, dtype=np.float64)
        confidence = np.full((3, 4), .8, dtype=np.float64)
        snapshots = [x.copy() for x in (*probabilities.values(), protect, confidence)]
        result = route_confidence_masks(
            probabilities, protect=protect, confidence=confidence
        )
        for original, snapshot in zip(
            (*probabilities.values(), protect, confidence), snapshots
        ):
            np.testing.assert_array_equal(original, snapshot)
        result["skin"][0, 0] = 0
        result["protect"][0, 0] = 1
        for original, snapshot in zip(
            (*probabilities.values(), protect, confidence), snapshots
        ):
            np.testing.assert_array_equal(original, snapshot)

    def test_strided_probability_and_protection_views_keep_exact_grid(self):
        source = np.full((8, 10), .95, dtype=np.float64)
        p = {
            "skin": source[::2, ::2],
            "hair": np.full((4, 5), .02),
            "fabric": np.full((4, 5), .01),
        }
        lock = np.zeros((8, 10), dtype=np.float64)
        lock[::2, ::2][0, 0] = 1
        result = route_confidence_masks(p, protect=lock[::2, ::2])
        self.assertEqual(result["skin"].shape, (4, 5))
        self.assertEqual(result["skin"][0, 0], 0)
        self.assertGreater(result["skin"][1, 1], 0)

    def test_nonfinite_confidence_and_protection_fail_closed(self):
        probabilities = {
            name: np.full((2, 2), value)
            for name, value in (("skin", .95), ("hair", .02), ("fabric", .01))
        }
        for bad in (np.nan, np.inf, -np.inf, -0.01, 1.01):
            for key in ("protect", "confidence"):
                with self.subTest(bad=bad, key=key):
                    kwargs = {"protect": np.zeros((2, 2))}
                    kwargs[key] = np.full((2, 2), bad)
                    with self.assertRaises(ValueError):
                        route_confidence_masks(probabilities, **kwargs)


if __name__ == "__main__":
    unittest.main()
