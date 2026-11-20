"""Metamorphic invariants for confidence routing, independent of model quality."""
import unittest

import numpy as np

from fidelis.studio.confidence_routing import CLASSES, route_confidence_masks


class ConfidenceMetamorphicTests(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(62026)
        self.probs = {name: rng.random((13, 11)) for name in CLASSES}
        self.protect = rng.random((13, 11))
        self.protect[::3, ::4] = 1
        self.certainty = rng.random((13, 11))

    def route(self, **kwargs):
        params = dict(protect=self.protect, confidence=self.certainty)
        params.update(kwargs)
        return route_confidence_masks(self.probs, **params)

    def test_relabeling_classes_only_relabels_outputs(self):
        original = self.route()
        rotated = dict(zip(CLASSES, (self.probs["fabric"], self.probs["skin"], self.probs["hair"])))
        renamed = route_confidence_masks(rotated, protect=self.protect, confidence=self.certainty)
        for target, source in zip(CLASSES, ("fabric", "skin", "hair")):
            np.testing.assert_array_equal(renamed[target], original[source])
        np.testing.assert_array_equal(renamed["protect"], original["protect"])

    def test_increasing_threshold_cannot_activate_new_pixels(self):
        low = self.route(threshold=0.55)
        high = self.route(threshold=0.90)
        for name in CLASSES:
            self.assertTrue(np.all((high[name] > 0) <= (low[name] > 0)))
            np.testing.assert_array_equal(high[name][high[name] > 0], low[name][high[name] > 0])

    def test_increasing_margin_cannot_activate_new_pixels(self):
        low = self.route(margin=0)
        high = self.route(margin=0.40)
        for name in CLASSES:
            self.assertTrue(np.all((high[name] > 0) <= (low[name] > 0)))

    def test_stronger_protection_never_increases_texture(self):
        low = self.route(protect=np.minimum(self.protect, 0.25))
        high = self.route(protect=np.maximum(self.protect, 0.75))
        for name in CLASSES:
            self.assertTrue(np.all(high[name] <= low[name] + np.float32(1e-7)))

    def test_lower_certainty_never_increases_texture(self):
        low = self.route(confidence=self.certainty * 0.25)
        high = self.route(confidence=self.certainty)
        for name in CLASSES:
            self.assertTrue(np.all(low[name] <= high[name]))
            self.assertTrue(np.all((low[name] > 0) <= (high[name] > 0)))


if __name__ == "__main__":
    unittest.main()
