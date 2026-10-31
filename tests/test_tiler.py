"""Regression tests for lossless tiled blending and fail-closed inference.

These use a deterministic nearest-neighbor tile function, so no GPU or model
weights are required. An identity-preserving upscale must not alter borders.
"""

import importlib.util
from pathlib import Path
import unittest

import numpy as np

# Import the NumPy-only tiler without initializing optional cv2/onnx packages.
tiler_path = Path(__file__).resolve().parents[1] / "fidelis/engine/tiler.py"
spec = importlib.util.spec_from_file_location("fidelis_tiler", tiler_path)
tiler_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tiler_module)
MultiDiffusionTiler = tiler_module.MultiDiffusionTiler
generate_cosine_weights = tiler_module.generate_cosine_weights


def repeat_upscale(tile, scale=2):
    return np.repeat(np.repeat(tile, scale, axis=0), scale, axis=1)


class TilerFidelityTests(unittest.TestCase):
    def test_cosine_preserves_every_pixel_including_outer_borders(self):
        source = np.arange(7 * 9 * 3, dtype=np.uint8).reshape(7, 9, 3)
        tiler = MultiDiffusionTiler(
            tile_size=8, overlap=4, scale=2, weight_type="cosine"
        )
        progress = []
        actual = tiler.process(source, repeat_upscale, progress.append)
        np.testing.assert_array_equal(actual, repeat_upscale(source))
        self.assertEqual(actual.shape, (14, 18, 3))
        self.assertEqual(progress[-1], 1.0)

    def test_cosine_preserves_grayscale_and_tiny_images(self):
        for source in (
            np.arange(5 * 7, dtype=np.uint8).reshape(5, 7),
            np.array([[211]], dtype=np.uint8),
        ):
            with self.subTest(shape=source.shape):
                tiler = MultiDiffusionTiler(
                    tile_size=8, overlap=4, scale=2, weight_type="cosine"
                )
                np.testing.assert_array_equal(
                    tiler.process(source, repeat_upscale),
                    repeat_upscale(source),
                )

    def test_gaussian_blending_remains_lossless_for_identity_upscale(self):
        source = np.arange(6 * 11 * 3, dtype=np.uint8).reshape(6, 11, 3)
        tiler = MultiDiffusionTiler(
            tile_size=8, overlap=4, scale=2, weight_type="gaussian"
        )
        np.testing.assert_array_equal(
            tiler.process(source, repeat_upscale), repeat_upscale(source)
        )

    def test_cosine_weights_are_positive_and_unfaded_on_canvas_perimeter(self):
        weights = generate_cosine_weights(3, 5, 8, 8)
        self.assertTrue(np.all(weights > 0))
        outer = generate_cosine_weights(
            3, 5, 8, 8,
            fade_top=False,
            fade_bottom=False,
            fade_left=False,
            fade_right=False,
        )
        np.testing.assert_array_equal(outer, np.ones((3, 5), dtype=np.float32))

    def test_custom_grid_has_no_gaps_for_small_tiles(self):
        grid = MultiDiffusionTiler.compute_tile_grid_custom(11, 13, 4, 3)
        coverage = np.zeros((11, 13), dtype=np.uint8)
        for y1, y2, x1, x2 in grid:
            coverage[y1:y2, x1:x2] = 1
        self.assertTrue(np.all(coverage == 1))

    def test_invalid_configuration_is_rejected(self):
        for kwargs in (
            {"tile_size": 2, "scale": 4},
            {"tile_size": 8, "overlap": 8},
            {"tile_size": 8, "overlap": -1},
            {"scale": 0},
            {"weight_type": "unknown"},
        ):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    MultiDiffusionTiler(**kwargs)

    def test_bad_model_dimensions_fail_closed(self):
        tiler = MultiDiffusionTiler(
            tile_size=8, overlap=4, scale=2, weight_type="cosine"
        )
        source = np.ones((6, 6, 3), dtype=np.uint8)
        with self.assertRaisesRegex(ValueError, "expected"):
            tiler.process(source, lambda tile: tile)

    def test_nonfinite_model_output_fails_closed(self):
        tiler = MultiDiffusionTiler(
            tile_size=8, overlap=4, scale=2, weight_type="cosine"
        )
        source = np.ones((6, 6, 3), dtype=np.uint8)

        def bad_tile(tile):
            result = repeat_upscale(tile).astype(np.float32)
            result[0, 0, 0] = np.nan
            return result

        with self.assertRaisesRegex(ValueError, "non-finite"):
            tiler.process(source, bad_tile)


if __name__ == "__main__":
    unittest.main()
