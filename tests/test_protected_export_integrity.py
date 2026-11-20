"""Regression tests for independent protected-export verification."""
import importlib.util
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'verify-protected-export.py'
SPEC = importlib.util.spec_from_file_location('verify_protected_export', SCRIPT)
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


class ProtectedExportVerificationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.base, self.output, self.mask = (root / name for name in ('base.png', 'out.png', 'mask.npz'))
        self.pixels = np.full((3, 4, 3), 50, dtype=np.uint8)
        self.protect = np.zeros((3, 4), dtype=np.float32)
        self.protect[1, 1] = 1
        self.protect[0, 0] = .5
        self.save()

    def save(self, pixels=None, protect=None):
        Image.fromarray(self.pixels).save(self.base)
        Image.fromarray(self.pixels if pixels is None else pixels).save(self.output)
        np.savez(self.mask, protect=self.protect if protect is None else protect)

    def test_unchanged_locked_pixel_passes(self):
        result = module.verify(self.base, self.output, self.mask)
        self.assertEqual((result['pass'], result['protected_pixels']), (True, 1))

    def test_changed_locked_pixel_fails(self):
        output = self.pixels.copy()
        output[1, 1, 0] += 1
        self.save(output)
        self.assertEqual(module.main([str(self.base), str(self.output), str(self.mask)]), 1)

    def test_changes_in_partial_and_unlocked_pixels_allowed(self):
        output = self.pixels.copy()
        output[0, 0] = 0
        output[2, 3] = 0
        self.save(output)
        self.assertTrue(module.verify(self.base, self.output, self.mask)['pass'])

    def test_dimension_mismatch_fails_closed(self):
        Image.fromarray(self.pixels[:2]).save(self.output)
        with self.assertRaisesRegex(ValueError, 'dimensions'):
            module.verify(self.base, self.output, self.mask)

    def test_invalid_masks_fail_closed(self):
        for invalid in (np.full((3, 4), np.nan), np.full((3, 4), 1.1), np.zeros((2, 4))):
            with self.subTest(mask=invalid.shape):
                self.save(protect=invalid)
                with self.assertRaises(ValueError):
                    module.verify(self.base, self.output, self.mask)

    def test_missing_protect_mask_fails_closed(self):
        np.savez(self.mask, fabric=self.protect)
        with self.assertRaisesRegex(ValueError, 'protect'):
            module.verify(self.base, self.output, self.mask)

    def test_empty_fully_locked_region_fails_closed(self):
        self.save(protect=np.zeros((3, 4), dtype=np.float32))
        with self.assertRaisesRegex(ValueError, 'no fully locked pixels'):
            module.verify(self.base, self.output, self.mask)

    def test_partially_locked_only_region_fails_closed(self):
        self.save(protect=np.full((3, 4), .5, dtype=np.float32))
        with self.assertRaisesRegex(ValueError, 'no fully locked pixels'):
            module.verify(self.base, self.output, self.mask)

    def test_boolean_and_complex_masks_fail_closed(self):
        for invalid in (self.protect.astype(bool), self.protect.astype(np.complex64)):
            with self.subTest(dtype=str(invalid.dtype)):
                self.save(protect=invalid)
                with self.assertRaisesRegex(ValueError, 'numeric HxW'):
                    module.verify(self.base, self.output, self.mask)

    def test_integer_binary_mask_supported(self):
        self.save(protect=self.protect.astype(np.uint8))
        self.assertEqual(module.verify(self.base, self.output, self.mask)['protected_pixels'], 1)

    def test_png_transparency_metadata_fails_closed(self):
        image = Image.fromarray(self.pixels)
        image.save(self.output, transparency=(50, 50, 50))
        with self.assertRaisesRegex(ValueError, 'transparency'):
            module.verify(self.base, self.output, self.mask)

    def test_nonidentity_exif_orientation_fails_closed(self):
        image = Image.fromarray(self.pixels)
        exif = Image.Exif()
        exif[274] = 6
        image.save(self.output, exif=exif)
        with self.assertRaisesRegex(ValueError, 'EXIF orientation'):
            module.verify(self.base, self.output, self.mask)

    def test_non_rgb_export_fails_closed(self):
        Image.fromarray(self.pixels[..., 0]).save(self.output)
        with self.assertRaisesRegex(ValueError, 'RGB'):
            module.verify(self.base, self.output, self.mask)


if __name__ == '__main__':
    unittest.main()
