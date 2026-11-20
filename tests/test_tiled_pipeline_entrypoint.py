"""Regression coverage for MEL-72 tiled pipeline entrypoint."""
import ast
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
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
        with TemporaryDirectory() as directory, patch("fidelis.core.pipeline.subprocess.run") as run:
            source = Path(directory) / "input.png"
            destination = Path(directory) / "output.png"
            run.return_value.returncode = 9
            run.return_value.stderr = "model unavailable"
            run.return_value.stdout = ""
            with self.assertRaisesRegex(RuntimeError, "Tiled upscale failed \\(9\\)"):
                pipeline._run_tiled_upscale(
                    source, destination,
                    "RealeSR-general-v3", 128, 16, 4,
                )
            cmd = run.call_args.args[0]
            self.assertTrue(cmd[1].endswith("scripts/tiled-upscale.py"))
            self.assertEqual(cmd[2:4], [str(source), str(destination)])
            self.assertEqual(cmd[-2:], ["--scale", "4"])


    def test_direct_success_without_output_is_rejected(self):
        pipeline = UpscalePipeline(cli_path="/unused/fidelis")
        with TemporaryDirectory() as directory, patch("fidelis.core.pipeline.subprocess.run") as run:
            run.return_value.returncode = 0
            output = Path(directory) / "missing.png"
            with self.assertRaisesRegex(RuntimeError, "Direct upscale reported success"):
                pipeline._run_direct_upscale(Path(directory) / "input.png", output, "Fake")
            run.assert_called_once()

    def test_direct_preexisting_output_is_rejected_without_invocation(self):
        pipeline = UpscalePipeline(cli_path="/unused/fidelis")
        with TemporaryDirectory() as directory, patch("fidelis.core.pipeline.subprocess.run") as run:
            output = Path(directory) / "stale.png"
            output.write_bytes(b"preserve me")
            with self.assertRaisesRegex(RuntimeError, "Direct upscale output path already exists"):
                pipeline._run_direct_upscale(Path(directory) / "input.png", output, "Fake")
            run.assert_not_called()
            self.assertEqual(output.read_bytes(), b"preserve me")

    def test_direct_symlink_output_is_rejected_after_subprocess(self):
        pipeline = UpscalePipeline(cli_path="/unused/fidelis")
        with TemporaryDirectory() as directory, patch("fidelis.core.pipeline.subprocess.run") as run:
            target = Path(directory) / "target.png"
            target.write_bytes(b"outside output")
            output = Path(directory) / "output.png"

            def create_symlink(*_args, **_kwargs):
                output.symlink_to(target)
                return type("Result", (), {"returncode": 0, "stderr": "", "stdout": ""})()

            run.side_effect = create_symlink
            with self.assertRaisesRegex(RuntimeError, "Direct upscale reported success"):
                pipeline._run_direct_upscale(Path(directory) / "input.png", output, "Fake")
            self.assertEqual(target.read_bytes(), b"outside output")

    def test_direct_success_with_fresh_output_is_accepted(self):
        pipeline = UpscalePipeline(cli_path="/unused/fidelis")
        with TemporaryDirectory() as directory, patch("fidelis.core.pipeline.subprocess.run") as run:
            output = Path(directory) / "result.png"

            def create_output(*_args, **_kwargs):
                output.write_bytes(b"new output")
                return type("Result", (), {"returncode": 0, "stderr": "", "stdout": ""})()

            run.side_effect = create_output
            pipeline._run_direct_upscale(Path(directory) / "input.png", output, "Fake")
            run.assert_called_once()
            self.assertEqual(output.read_bytes(), b"new output")

    def test_success_without_output_is_rejected(self):
        pipeline = UpscalePipeline(cli_path="/unused/fidelis")
        with TemporaryDirectory() as directory, patch("fidelis.core.pipeline.subprocess.run") as run:
            run.return_value.returncode = 0
            source = Path(directory) / "source.png"
            output = Path(directory) / "missing.png"
            with self.assertRaisesRegex(RuntimeError, "without a nonempty output file"):
                pipeline._run_tiled_upscale(source, output, "RealeSR-general-v3", 128, 16, 4)

    def test_success_with_empty_output_is_rejected(self):
        pipeline = UpscalePipeline(cli_path="/unused/fidelis")
        with TemporaryDirectory() as directory, patch("fidelis.core.pipeline.subprocess.run") as run:
            source = Path(directory) / "source.png"
            output = Path(directory) / "empty.png"

            def create_empty_output(*_args, **_kwargs):
                output.touch()
                return type("Result", (), {"returncode": 0, "stderr": "", "stdout": ""})()

            run.side_effect = create_empty_output
            with self.assertRaisesRegex(RuntimeError, "without a nonempty output file"):
                pipeline._run_tiled_upscale(source, output, "RealeSR-general-v3", 128, 16, 4)

    def test_preexisting_output_is_rejected_without_running_subprocess(self):
        pipeline = UpscalePipeline(cli_path="/unused/fidelis")
        with TemporaryDirectory() as directory, patch("fidelis.core.pipeline.subprocess.run") as run:
            source = Path(directory) / "source.png"
            output = Path(directory) / "stale.png"
            output.write_bytes(b"old successful output")
            with self.assertRaisesRegex(RuntimeError, "output path already exists"):
                pipeline._run_tiled_upscale(source, output, "RealeSR-general-v3", 128, 16, 4)
            run.assert_not_called()
            self.assertEqual(output.read_bytes(), b"old successful output")

    def test_preexisting_output_symlink_is_rejected(self):
        pipeline = UpscalePipeline(cli_path="/unused/fidelis")
        with TemporaryDirectory() as directory, patch("fidelis.core.pipeline.subprocess.run") as run:
            source = Path(directory) / "source.png"
            target = Path(directory) / "target.png"
            target.write_bytes(b"protected artifact")
            output = Path(directory) / "output.png"
            output.symlink_to(target)
            with self.assertRaisesRegex(RuntimeError, "output path already exists"):
                pipeline._run_tiled_upscale(source, output, "RealeSR-general-v3", 128, 16, 4)
            run.assert_not_called()
            self.assertEqual(target.read_bytes(), b"protected artifact")

    def test_subprocess_symlink_output_is_not_accepted_as_fresh_artifact(self):
        pipeline = UpscalePipeline(cli_path="/unused/fidelis")
        with TemporaryDirectory() as directory, patch("fidelis.core.pipeline.subprocess.run") as run:
            source = Path(directory) / "source.png"
            target = Path(directory) / "external.png"
            target.write_bytes(b"existing artifact")
            output = Path(directory) / "output.png"

            def create_link(*_args, **_kwargs):
                output.symlink_to(target)
                return type("Result", (), {"returncode": 0, "stderr": "", "stdout": ""})()

            run.side_effect = create_link
            with self.assertRaisesRegex(RuntimeError, "without a nonempty output file"):
                pipeline._run_tiled_upscale(source, output, "RealeSR-general-v3", 128, 16, 4)
            self.assertEqual(target.read_bytes(), b"existing artifact")

    def test_success_with_nonempty_output_is_accepted(self):
        pipeline = UpscalePipeline(cli_path="/unused/fidelis")
        with TemporaryDirectory() as directory, patch("fidelis.core.pipeline.subprocess.run") as run:
            source = Path(directory) / "source.png"
            output = Path(directory) / "result.png"

            def create_output(*_args, **_kwargs):
                output.write_bytes(b"placeholder artifact")
                return type("Result", (), {"returncode": 0, "stderr": "", "stdout": ""})()

            run.side_effect = create_output
            pipeline._run_tiled_upscale(source, output, "RealeSR-general-v3", 128, 16, 4)
            run.assert_called_once()
            self.assertEqual(output.read_bytes(), b"placeholder artifact")


if __name__ == "__main__":
    unittest.main()
