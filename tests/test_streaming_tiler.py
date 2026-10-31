"""Deterministic GPU-free regression tests for streamed tile composition."""
import tempfile
from pathlib import Path
import unittest
import numpy as np
from fidelis.engine.tiler import MultiDiffusionTiler
from fidelis.engine.streaming import process_streamed


def upscale(tile, scale=2):
    return np.repeat(np.repeat(tile, scale, axis=0), scale, axis=1)


class StreamingTests(unittest.TestCase):
    def test_matches_existing_full_frame_tiler(self):
        for weight in ("cosine", "gaussian"):
            for shape in ((1, 1), (5, 7), (17, 13), (25, 29)):
                with self.subTest(weight=weight, shape=shape):
                    image = np.arange(shape[0] * shape[1] * 3, dtype=np.uint32)
                    image = (image % 256).astype(np.uint8).reshape(*shape, 3)
                    tiler = MultiDiffusionTiler(tile_size=12, overlap=4, scale=2, weight_type=weight)
                    expected = tiler.process(image, upscale)
                    with tempfile.TemporaryDirectory() as d:
                        output = process_streamed(tiler, image, upscale, Path(d) / "image.bin")
                        self.assertIsInstance(output, np.memmap)
                        np.testing.assert_array_equal(output, expected)

    def test_grayscale_and_progress(self):
        image = np.arange(11 * 19, dtype=np.uint8).reshape(11, 19)
        tiler = MultiDiffusionTiler(tile_size=12, overlap=4, scale=2, weight_type="cosine")
        progress = []
        with tempfile.TemporaryDirectory() as d:
            result = process_streamed(tiler, image, upscale, Path(d) / "gray.bin", progress.append)
            np.testing.assert_array_equal(result, upscale(image))
            self.assertEqual(progress[-1], 1.0)

    def test_invalid_model_tile_fails_and_removes_partial_disk_file(self):
        image = np.ones((9, 9, 3), dtype=np.uint8)
        tiler = MultiDiffusionTiler(tile_size=12, overlap=4, scale=2)
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "broken.bin"
            with self.assertRaisesRegex(ValueError, "expected"):
                process_streamed(tiler, image, lambda tile: tile, path)
            self.assertFalse(path.exists())

    def test_nonfinite_output_fails_closed(self):
        image = np.ones((9, 9), dtype=np.uint8)
        tiler = MultiDiffusionTiler(tile_size=12, overlap=4, scale=2)
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "bad.bin"
            def corrupt(tile):
                result = upscale(tile).astype(np.float32)
                result[0, 0] = np.nan
                return result
            with self.assertRaisesRegex(ValueError, "non-finite"):
                process_streamed(tiler, image, corrupt, path)
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
