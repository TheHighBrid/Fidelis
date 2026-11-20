"""Deterministic property tests for confidence-gated semantic mask routing.

These fixtures test algebraic safety invariants, not segmentation quality.
"""
import unittest
import numpy as np
from fidelis.studio.confidence_routing import route_confidence_masks


class RandomizedRoutingInvariants(unittest.TestCase):
    def test_randomized_maps_never_leak_or_cross_classes(self):
        rng = np.random.default_rng(62019)
        classes = ("skin", "hair", "fabric")
        for _ in range(24):
            values = rng.random((3, 17, 23))
            protect = rng.random((17, 23))
            protect[::3, ::4] = 1.0
            confidence = rng.random((17, 23))
            probabilities = dict(zip(classes, values))
            original = {key: val.copy() for key, val in probabilities.items()}
            result = route_confidence_masks(probabilities, protect=protect, confidence=confidence)
            weights = np.stack([result[key] for key in classes])
            self.assertTrue(np.all(np.isfinite(weights)))
            self.assertTrue(np.all(weights >= 0))
            self.assertTrue(np.all(weights <= 1))
            self.assertTrue(np.all(np.count_nonzero(weights, axis=0) <= 1))
            self.assertTrue(np.all(weights[:, result["protect"] == 1] == 0))
            self.assertTrue(np.all(weights.sum(axis=0) <= 1 - result["protect"] + 1e-6))
            for key in classes:
                np.testing.assert_array_equal(probabilities[key], original[key])

    def test_tightening_confidence_and_margin_never_adds_texture(self):
        rng = np.random.default_rng(62020)
        probabilities = {key: rng.random((31, 29)) for key in ("skin", "hair", "fabric")}
        protect = rng.random((31, 29))
        def total(**kwargs):
            result = route_confidence_masks(probabilities, protect=protect, **kwargs)
            return result["skin"] + result["hair"] + result["fabric"]
        baseline = total(threshold=.4, margin=.02)
        strict = total(threshold=.85, margin=.3)
        self.assertTrue(np.all(strict <= baseline + 1e-7))

    def test_output_protection_quantization_matches_attenuation(self):
        rng = np.random.default_rng(62021)
        protect = rng.random((37, 19))
        protect[0, :3] = [1, np.nextafter(1., 0.), 0]
        probabilities = {
            "skin": np.full(protect.shape, .95),
            "hair": np.full(protect.shape, .01),
            "fabric": np.full(protect.shape, .01),
        }
        result = route_confidence_masks(probabilities, protect=protect)
        expected = (.95 * (1 - result["protect"].astype(np.float64))).astype(np.float32)
        np.testing.assert_allclose(result["skin"], expected, rtol=1e-6, atol=1e-7)
        self.assertEqual(float(result["skin"][0, 1]), 0.)


if __name__ == "__main__":
    unittest.main()
