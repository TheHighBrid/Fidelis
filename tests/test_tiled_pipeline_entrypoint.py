"""Regression coverage for MEL-72 tiled pipeline entrypoint."""
import ast
from pathlib import Path
import unittest
from unittest.mock import patch

from fidelis.core.pipeline import UpscalePipeline


PIPELINE_PATH = Path(__file__).resolve().parents[1] / "fidelis" / "core" / "pipeline.py"


class TiledPipelineEntrypointTests(unittest.TestCase):
    def test_run_does_not_import_nonexistent_tiled_module(self):
        # The tracked implementation is scripts/tiled-upscale.py, not an
        # importable scripts.tiled_upscale module.
        source = ast.parse(PIPELINE_PATH.read_text(encoding="utf-8"))
        run = next(n for n in ast.walk(source)
                   if isinstance(n, ast.FunctionDef) and n.name == "run")
        imports = [n.module for n in ast.walk(run) if isinstance(n, ast.ImportFrom)]
        self.assertNotIn("scripts", imports)

    def test_tiled_subprocess_uses_tracked_script_and_checks_failure(self):
        pipeline = UpscalePipeline(cli_path="/unused/fidelis")
        with patch("fidelis.core.pipeline.subprocess.run") as run:
            run.return_value.returncode = 9
            run.return_value.stderr = "model unavailable"
            run.return_value.stdout = ""
            with self.assertRaisesRegex(RuntimeError, "Tiled upscale failed \\(9\\)"):
                pipeline._run_tiled_upscale(
                    Path("/tmp/input.png"), Path("/tmp/output.png"),
                    "RealeSR-general-v3", 128, 16, 4,
                )
            cmd = run.call_args.args[0]
            self.assertTrue(cmd[1].endswith("scripts/tiled-upscale.py"))
            self.assertEqual(cmd[2:4], ["/tmp/input.png", "/tmp/output.png"])
            self.assertEqual(cmd[-2:], ["--scale", "4"])


if __name__ == "__main__":
    unittest.main()
