"""Pixel locks and fail-closed masks are independent of model quality."""
from pathlib import Path
import json
import subprocess
import sys
import tempfile
import unittest

import numpy as np
from PIL import Image

from fidelis.postprocess.regions import PROFILES, RegionBlend, compose_regions


class RegionTests(unittest.TestCase):
    def setUp(self):
        self.base = np.random.default_rng(4).integers(0, 256, (7, 9, 3), dtype=np.uint8)
        self.texture = 255 - self.base
        self.ones = np.ones((7, 9), dtype=np.float32)

    def test_unknown_and_missing_confidence_preserve_base(self):
        for masks in ({}, {"skin": self.ones}, {"confidence": self.ones}):
            actual, alpha = compose_regions(self.base, self.texture, **masks)
            np.testing.assert_array_equal(actual, self.base)
            self.assertFalse(alpha.any())

    def test_protection_wins_over_all_overlapping_regions(self):
        protection = np.zeros_like(self.ones)
        protection[:, 2:5] = 1
        actual, alpha = compose_regions(
            self.base, self.texture, skin=self.ones, hair=self.ones, fabric=self.ones,
            protected=protection, confidence=self.ones, blend=RegionBlend(1, 1, 1))
        np.testing.assert_array_equal(actual[:, 2:5], self.base[:, 2:5])
        np.testing.assert_array_equal(actual[:, :2], self.texture[:, :2])
        self.assertTrue(np.all(alpha <= 1))

    def test_linear_light_midpoint(self):
        actual, _ = compose_regions(np.zeros_like(self.base), np.full_like(self.base, 255),
                                    skin=self.ones, confidence=self.ones, blend=RegionBlend(.5, 0, 0))
        self.assertTrue(np.all(actual == 188))

    def test_zero_confidence_and_strict_profile(self):
        for kwargs in ({"confidence": self.ones * 0}, {"blend": PROFILES["packshot_strict"]}):
            masks = {"skin": self.ones, "confidence": self.ones, **kwargs}
            actual, _ = compose_regions(self.base, self.texture, **masks)
            np.testing.assert_array_equal(actual, self.base)

    def test_edge_guard_attenuates_without_classifying_hardware(self):
        _, alpha = compose_regions(self.base, self.texture, fabric=self.ones,
                                   confidence=self.ones, edge_guard=self.ones,
                                   blend=RegionBlend(0, 0, 1, .75))
        np.testing.assert_allclose(alpha, .25)

    def test_rejects_malformed_masks_and_passes(self):
        for mask in (self.ones * np.nan, self.ones * np.inf, self.ones * -1,
                     self.ones * 1.01, self.ones[:2], np.full((7, 9), "bad")):
            with self.subTest(mask=str(mask.dtype)):
                with self.assertRaises(ValueError):
                    compose_regions(self.base, self.texture, skin=mask)
        for texture in (self.texture[:2], self.texture.astype(np.float32)):
            with self.assertRaises(ValueError):
                compose_regions(self.base, texture)
        for value in (float("nan"), -1, 1.1):
            with self.assertRaises(ValueError):
                RegionBlend(skin=value)

    def test_cli_exports_exact_protection_and_unsigned_recipe(self):
        script = Path(__file__).resolve().parents[1] / "scripts/reblend-regions.py"
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            Image.fromarray(self.base).save(root / "base.png")
            Image.fromarray(self.texture).save(root / "texture.png")
            np.savez(root / "masks.npz", skin=self.ones, confidence=self.ones,
                     protected=self.ones)
            command = [sys.executable, str(script), str(root / "base.png"),
                       str(root / "texture.png"), str(root / "out.png"),
                       "--masks", str(root / "masks.npz")]
            subprocess.run(command, check=True, capture_output=True, text=True)
            with Image.open(root / "out.png") as image:
                np.testing.assert_array_equal(np.array(image), self.base)
            recipe = json.loads((root / "out.png.recipe.json").read_text())
            self.assertFalse(recipe["inference_executed"])
            self.assertEqual(recipe["provenance"], "unsigned_execution_record")
            self.assertEqual(len(recipe["output_sha256"]), 64)
            command[-1] = str(root / "missing.npz")
            self.assertNotEqual(subprocess.run(command, capture_output=True).returncode, 0)


if __name__ == "__main__":
    unittest.main()
