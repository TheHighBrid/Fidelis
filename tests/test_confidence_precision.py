"""Precision-boundary regressions for confidence-gated semantic routing."""
import unittest

import numpy as np

from fidelis.studio.confidence_routing import route_confidence_masks


class ConfidencePrecisionTests(unittest.TestCase):
    def route(self, skin, hair=0.05, fabric=0.05, **kwargs):
        probabilities = {
            name: np.array([[value]], dtype=np.float64)
            for name, value in (("skin", skin), ("hair", hair), ("fabric", fabric))
        }
        return route_confidence_masks(
            probabilities, protect=np.zeros((1, 1), dtype=np.float64), **kwargs
        )

    def test_below_threshold_does_not_round_up_to_acceptance(self):
        self.assertEqual(float(self.route(0.79999999)["skin"][0, 0]), 0.0)

    def test_margin_uses_unrounded_probabilities(self):
        self.assertEqual(float(self.route(0.9, hair=0.75000001)["skin"][0, 0]), 0.0)

    def test_distinct_close_probabilities_not_mistaken_for_tie(self):
        result = self.route(0.90000001, hair=0.9, margin=0)
        self.assertGreater(float(result["skin"][0, 0]), 0.0)
        self.assertEqual(float(result["hair"][0, 0]), 0.0)

    def test_protection_rounding_to_one_zeroes_all_texture_masks(self):
        probabilities = {name: np.array([[value]], dtype=np.float64)
                         for name, value in (("skin", 0.99), ("hair", 0.01), ("fabric", 0.01))}
        result = route_confidence_masks(
            probabilities, protect=np.array([[1.0 - 1e-9]], dtype=np.float64)
        )
        self.assertEqual(float(result["protect"][0, 0]), 1.0)
        for name in ("skin", "hair", "fabric"):
            self.assertEqual(float(result[name][0, 0]), 0.0)

    def test_near_one_protection_not_rounded_up_still_attenuates(self):
        probabilities = {name: np.array([[value]], dtype=np.float64)
                         for name, value in (("skin", 0.99), ("hair", 0.01), ("fabric", 0.01))}
        result = route_confidence_masks(
            probabilities, protect=np.array([[1.0 - 1e-5]], dtype=np.float64)
        )
        self.assertLess(float(result["protect"][0, 0]), 1.0)
        self.assertGreater(float(result["skin"][0, 0]), 0.0)

    def test_texture_attenuation_matches_exported_protection_precision(self):
        probabilities = {
            "skin": np.array([[0.95, 0.95]], dtype=np.float64),
            "hair": np.array([[0.01, 0.01]], dtype=np.float64),
            "fabric": np.array([[0.01, 0.01]], dtype=np.float64),
        }
        protection = np.array([[0.123456789123, 0.9999999]], dtype=np.float64)
        result = route_confidence_masks(probabilities, protect=protection)
        expected = (
            probabilities["skin"] * (1.0 - result["protect"].astype(np.float64))
        ).astype(np.float32)
        np.testing.assert_array_equal(result["skin"], expected)
        np.testing.assert_array_equal(result["hair"], np.zeros((1, 2), dtype=np.float32))
        np.testing.assert_array_equal(result["fabric"], np.zeros((1, 2), dtype=np.float32))

    def test_zero_confidence_still_preserves_exported_protection(self):
        probabilities = {
            name: np.array([[value]], dtype=np.float64)
            for name, value in (("skin", 0.95), ("hair", 0.01), ("fabric", 0.01))
        }
        result = route_confidence_masks(
            probabilities,
            protect=np.array([[0.123456789123]], dtype=np.float64),
            confidence=np.zeros((1, 1), dtype=np.float64),
        )
        self.assertEqual(float(result["skin"][0, 0]), 0.0)
        self.assertEqual(result["protect"][0, 0], np.float32(0.123456789123))

    def test_output_contract_remains_float32(self):
        result = self.route(0.9)
        self.assertTrue(all(mask.dtype == np.float32 for mask in result.values()))


if __name__ == "__main__":
    unittest.main()
