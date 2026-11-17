"""Regression checks for exclusive streamed-output ownership."""
import tempfile
import unittest
from pathlib import Path

import numpy as np

from fidelis.engine.streaming import process_streamed
from fidelis.engine.tiler import MultiDiffusionTiler


class StreamingOutputOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "export.raw"
        self.image = np.arange(12, dtype=np.uint8).reshape(2, 2, 3)
        self.tiler = MultiDiffusionTiler(tile_size=4, overlap=0, scale=2)

    def upscale(self, tile):
        return np.repeat(np.repeat(tile, 2, axis=0), 2, axis=1)

    def test_existing_output_is_not_overwritten_or_deleted(self):
        self.path.write_bytes(b"irreplaceable original bytes")
        with self.assertRaises(FileExistsError):
            process_streamed(self.tiler, self.image, self.upscale, self.path)
        self.assertEqual(self.path.read_bytes(), b"irreplaceable original bytes")

    def test_new_output_is_created_and_contains_expected_pixels(self):
        output = process_streamed(self.tiler, self.image, self.upscale, self.path)
        np.testing.assert_array_equal(output, self.upscale(self.image))
        self.assertEqual(self.path.stat().st_size, 4 * 4 * 3)

    def test_failed_tile_removes_only_newly_created_output(self):
        def fail(_tile):
            raise RuntimeError("failed inference")
        with self.assertRaisesRegex(RuntimeError, "failed inference"):
            process_streamed(self.tiler, self.image, fail, self.path)
        self.assertFalse(self.path.exists())

    def test_existing_output_does_not_invoke_model(self):
        self.path.write_bytes(b"keep")
        def fail(_tile):
            self.fail("model must not run if destination exists")
        with self.assertRaises(FileExistsError):
            process_streamed(self.tiler, self.image, fail, self.path)
        self.assertEqual(self.path.read_bytes(), b"keep")


if __name__ == "__main__":
    unittest.main()
