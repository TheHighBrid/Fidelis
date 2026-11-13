"""Pixel locks and fail-closed masks are independent of model quality."""
import io
from pathlib import Path
import json
import subprocess
import sys
import tempfile
import unittest

import numpy as np
from PIL import Image, ImageCms

from fidelis.studio.png import read_export_pass, read_rgb8_png, write_rgb_png

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

    def test_cli_uint16_straight_alpha_and_exact_protection(self):
        import cv2

        script = Path(__file__).resolve().parents[1] / "scripts/reblend-regions.py"
        base = np.dstack((self.base.astype(np.uint16) * 251 + 123,
                          np.full(self.ones.shape, 31415, dtype=np.uint16)))
        base[:, 0, 3] = 0
        texture = np.full_like(base[:, :, :3], 53000)
        protection = np.zeros_like(self.ones)
        protection[:, 1] = 1
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name, pixels, channel_order in (("base", base, [2, 1, 0, 3]),
                                                ("texture", texture, [2, 1, 0])):
                self.assertTrue(cv2.imwrite(str(root / f"{name}.png"), pixels[:, :, channel_order]))
            with (root / "texture.png").open("rb") as stream:
                with self.assertRaisesRegex(ValueError, "8-bit RGB"):
                    read_rgb8_png(stream)
            np.savez(root / "masks.npz", confidence=self.ones, skin=self.ones, protected=protection)
            output = root / "out.png"
            command = [sys.executable, str(script), str(root / "base.png"), str(root / "texture.png"),
                       str(output), "--masks", str(root / "masks.npz"), "--skin", "0.5"]
            subprocess.run(command, check=True, capture_output=True, text=True)
            actual = cv2.imread(str(output), cv2.IMREAD_UNCHANGED)[:, :, [2, 1, 0, 3]]
            self.assertEqual(actual.dtype, np.uint16)
            np.testing.assert_array_equal(actual[:, :2], base[:, :2])
            np.testing.assert_array_equal(actual[:, :, 3], base[:, :, 3])
            values = base[:, 2:, :3] / 65535
            linear_base = np.where(values <= .04045, values / 12.92, ((values + .055) / 1.055) ** 2.4)
            linear_mean = (linear_base + ((53000 / 65535 + .055) / 1.055) ** 2.4) / 2
            self.assertTrue(np.any(actual[:, 2:, :3] % 257 != 0))
            np.testing.assert_allclose(actual[:, 2:, :3],
                                       np.rint((1.055 * linear_mean ** (1 / 2.4) - .055) * 65535), atol=1)
            failure = subprocess.run(command + ["--depth", "8"], capture_output=True, text=True)
            self.assertNotEqual(failure.returncode, 0)
            self.assertIn("discard input precision", failure.stderr)

    def test_icc_conversion_requires_explicit_opt_in_and_preserves_alpha(self):
        rgba = np.dstack((self.base, self.texture[:, :, 0]))
        icc = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "rgba.png"
            Image.fromarray(rgba).save(path, icc_profile=icc)
            with self.assertRaisesRegex(ValueError, "opt into"):
                read_export_pass(path, allow_alpha=True)
            result, converted = read_export_pass(path, allow_alpha=True, convert_icc=True)
            self.assertTrue(converted)
            np.testing.assert_array_equal(result, rgba)

    def test_rgb8_canonical_export_remains_importable(self):
        stream = io.BytesIO()
        write_rgb_png(self.base, stream)
        stream.seek(0)
        np.testing.assert_array_equal(read_rgb8_png(stream), self.base)


if __name__ == "__main__":
    unittest.main()
