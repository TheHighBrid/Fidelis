"""Fail-closed fixture tests for F09/MEL-62 semantic mask routing."""
import unittest
import numpy as np
from fidelis.studio.confidence_routing import route_confidence_masks


class ConfidenceRoutingTests(unittest.TestCase):
    def masks(self, skin, hair=0.05, fabric=0.05, protect=0.0, **kw):
        p = {name: np.array([[value]], dtype=float) for name, value in
             (("skin", skin), ("hair", hair), ("fabric", fabric))}
        return route_confidence_masks(p, protect=np.array([[protect]]), **kw)

    def test_confident_class_routes_only_to_winner(self):
        m = self.masks(.92)
        self.assertAlmostEqual(float(m["skin"][0, 0]), .92, places=6)
        self.assertEqual(float(m["hair"][0, 0]), 0)
        self.assertEqual(float(m["fabric"][0, 0]), 0)

    def test_low_confidence_keeps_base(self):
        self.assertEqual(float(self.masks(.79)["skin"][0, 0]), 0)

    def test_ambiguous_class_keeps_base(self):
        self.assertEqual(float(self.masks(.91, hair=.85)["skin"][0, 0]), 0)

    def test_full_protection_wins(self):
        m = self.masks(.99, protect=1)
        self.assertEqual(sum(float(m[k][0, 0]) for k in ("skin", "hair", "fabric")), 0)

    def test_partial_protection_and_confidence_attenuate(self):
        m = self.masks(.9, protect=.5, confidence=np.array([[.4]]))
        self.assertAlmostEqual(float(m["skin"][0, 0]), .18, places=6)

    def test_no_background_to_fabric_guess(self):
        m = self.masks(.05, hair=.02, fabric=.07)
        self.assertEqual(float(m["fabric"][0, 0]), 0)

    def test_nan_or_out_of_range_rejected(self):
        for value in (float("nan"), float("inf"), -.1, 1.1):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.masks(value)

    def test_misaligned_and_missing_class_rejected(self):
        p = {"skin": np.zeros((2, 2)), "hair": np.zeros((2, 2)), "fabric": np.zeros((2, 3))}
        with self.assertRaises(ValueError):
            route_confidence_masks(p, protect=np.zeros((2, 2)))
        del p["fabric"]
        with self.assertRaises(ValueError):
            route_confidence_masks(p, protect=np.zeros((2, 2)))

    def test_invalid_threshold_and_margin_rejected(self):
        for kwargs in ({"threshold": 0}, {"threshold": float("nan")}, {"margin": -1}, {"margin": 1.1}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.masks(.9, **kwargs)

    def test_ties_fail_closed(self):
        m = self.masks(.9, hair=.9, margin=0)
        self.assertEqual(float(m["skin"][0, 0]), 0)


if __name__ == "__main__":
    unittest.main()
