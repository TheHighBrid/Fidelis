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

    def test_output_contract_remains_float32(self):
        result = self.route(0.9)
        self.assertTrue(all(mask.dtype == np.float32 for mask in result.values()))


if __name__ == "__main__":
    unittest.main()
