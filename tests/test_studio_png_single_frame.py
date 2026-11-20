"""Regression tests: Studio import must not silently select APNG frame zero."""

import io
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from fidelis.studio.png import read_export_pass, read_rgb8_png


def _png_bytes(animated):
    first = Image.new("RGB", (8, 8), (20, 30, 40))
    stream = io.BytesIO()
    if animated:
        second = Image.new("RGB", (8, 8), (220, 30, 40))
        first.save(stream, format="PNG", save_all=True, append_images=[second],
                   duration=[100, 100], loop=0)
    else:
        first.save(stream, format="PNG")
    return stream.getvalue()


class StudioPngSingleFrameTests(unittest.TestCase):
    def test_rgb8_import_rejects_apng(self):
        payload = _png_bytes(True)
        with Image.open(io.BytesIO(payload)) as image:
            self.assertGreater(image.n_frames, 1)
        with self.assertRaisesRegex(ValueError, "multi-frame"):
            read_rgb8_png(io.BytesIO(payload))

    def test_export_pass_rejects_apng(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "animated.png"
            path.write_bytes(_png_bytes(True))
            with self.assertRaisesRegex(ValueError, "multi-frame"):
                read_export_pass(path)

    def test_export_pass_rejects_apng_with_alpha_enabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "animated.png"
            path.write_bytes(_png_bytes(True))
            with self.assertRaisesRegex(ValueError, "multi-frame"):
                read_export_pass(path, allow_alpha=True, convert_icc=True)

    def test_single_frame_rgba_export_still_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "still_rgba.png"
            Image.new("RGBA", (8, 8), (20, 30, 40, 128)).save(path)
            actual, converted = read_export_pass(path, allow_alpha=True)
            self.assertFalse(converted)
            self.assertEqual(actual.shape, (8, 8, 4))
            np.testing.assert_array_equal(actual[0, 0], (20, 30, 40, 128))

    def test_single_frame_rgb_still_accepted(self):
        payload = _png_bytes(False)
        actual = read_rgb8_png(io.BytesIO(payload))
        self.assertEqual(actual.shape, (8, 8, 3))
        np.testing.assert_array_equal(actual[0, 0], (20, 30, 40))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "still.png"
            path.write_bytes(payload)
            exported, converted = read_export_pass(path)
            self.assertFalse(converted)
            np.testing.assert_array_equal(exported, actual)


if __name__ == "__main__":
    unittest.main()
