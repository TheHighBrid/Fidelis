"""GPU-free integration checks for the actual fidelis upscale --tiled path."""

import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image


script_path = Path(__file__).resolve().parents[1] / "scripts/tiled-upscale.py"
spec = importlib.util.spec_from_file_location("fidelis_tiled_cli", script_path)
tiled_cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tiled_cli)


def fake_ncnn_call(command, **_kwargs):
    # Emulate the existing 4x NCNN CLI using a deterministic, pixel-faithful model.
    assert command[1] == "upscale"
    with Image.open(command[2]) as source:
        arr = np.asarray(source.convert("RGB"))
    result = np.repeat(np.repeat(arr, 4, axis=0), 4, axis=1)
    Image.fromarray(result).save(command[3])


class CliTiledFidelityTests(unittest.TestCase):
    def test_live_cli_tiling_preserves_rgb_and_canvas_perimeter(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = np.arange(13 * 17 * 3, dtype=np.uint8).reshape(13, 17, 3)
            input_path = Path(tmp) / "source.png"
            output_path = Path(tmp) / "output.png"
            Image.fromarray(source).save(input_path)

            with patch.object(tiled_cli.subprocess, "check_call", side_effect=fake_ncnn_call):
                tiled_cli.tiled_upscale(
                    input_path, output_path, model="Fake",
                    tile_size=8, overlap=3, scale=4, cli_path="fake",
                )
            with Image.open(output_path) as result:
                actual = np.asarray(result.convert("RGB"))
            expected = np.repeat(np.repeat(source, 4, axis=0), 4, axis=1)
            np.testing.assert_array_equal(actual, expected)

    def test_short_image_axis_smaller_than_overlap(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = np.full((3, 15, 3), 173, dtype=np.uint8)
            input_path = Path(tmp) / "source.png"
            output_path = Path(tmp) / "output.png"
            Image.fromarray(source).save(input_path)

            with patch.object(tiled_cli.subprocess, "check_call", side_effect=fake_ncnn_call):
                tiled_cli.tiled_upscale(
                    input_path, output_path, model="Fake",
                    tile_size=8, overlap=6, scale=4, cli_path="fake",
                )
            with Image.open(output_path) as result:
                actual = np.asarray(result.convert("RGB"))
            self.assertEqual(actual.shape, (12, 60, 3))
            self.assertTrue(np.all(actual == 173))

    def test_direct_one_tile_4x_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = np.full((4, 5, 3), 211, dtype=np.uint8)
            input_path = Path(tmp) / "source.png"
            output_path = Path(tmp) / "output.png"
            Image.fromarray(source).save(input_path)

            with patch.object(tiled_cli.subprocess, "check_call", side_effect=fake_ncnn_call):
                tiled_cli.tiled_upscale(
                    input_path, output_path, model="Fake",
                    tile_size=8, overlap=3, scale=4, cli_path="fake",
                )
            with Image.open(output_path) as result:
                self.assertEqual(result.size, (20, 16))

    def test_invalid_runtime_contract_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            inp = Path(tmp) / "source.png"
            out = Path(tmp) / "output.png"
            for kwargs in (
                {"tile_size": 0},
                {"tile_size": 8, "overlap": 8},
                {"tile_size": 8, "overlap": -1},
                {"scale": 2},
            ):
                with self.subTest(kwargs=kwargs):
                    with self.assertRaises(ValueError):
                        tiled_cli.tiled_upscale(inp, out, cli_path="fake", **kwargs)

    def test_invalid_model_tile_dimensions_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = np.full((13, 17, 3), 91, dtype=np.uint8)
            inp = Path(tmp) / "source.png"
            out = Path(tmp) / "output.png"
            Image.fromarray(source).save(inp)

            def bad_model(command, **_kwargs):
                Image.new("RGB", (1, 1), (0, 0, 0)).save(command[3])

            with patch.object(tiled_cli.subprocess, "check_call", side_effect=bad_model):
                with self.assertRaisesRegex(ValueError, "expected"):
                    tiled_cli.tiled_upscale(
                        inp, out, model="Fake",
                        tile_size=8, overlap=3, scale=4, cli_path="fake",
                    )
            self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()
