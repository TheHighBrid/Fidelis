"""Exercise the actual native dispatcher argument and temporary-file boundary."""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class NativePreviewWrapperTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.runtime = self.root / "runtime with spaces"
        self.runtime.mkdir()
        self.wrapper = self.runtime / "realsr-ncnn"
        shutil.copyfile(ROOT / "scripts/ncnn-preview-runtime.sh", self.wrapper)
        self.wrapper.chmod(0o755)
        self.model = self.runtime / "models-RealeSR-general-v3"
        self.model.mkdir()
        for name in ("x4.param", "x4.bin"):
            (self.model / name).write_bytes(b"fixture weights, not inference")
        self.record = self.root / "arguments"
        binary = self.runtime / "realesrgan-binary"
        binary.write_text('#!/bin/bash\nprintf "%s\\0" "$@" > "$RECORD"\nexit "${FAKE_EXIT:-0}"\n')
        binary.chmod(0o755)
        self.env = dict(os.environ, RECORD=str(self.record), TMPDIR=str(self.root))

    def command(self):
        return ["bash", str(self.wrapper), "-i", "input with spaces.png", "-o", "output with spaces.png",
                "-m", str(self.model), "-s", "4", "-t", "192"]

    def test_exact_arguments_and_cleanup_after_success(self):
        run = subprocess.run(self.command(), env=self.env, capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        args = self.record.read_bytes().decode().rstrip("\0").split("\0")
        self.assertEqual(args[:4], ["-i", "input with spaces.png", "-o", "output with spaces.png"])
        self.assertEqual(args[6:], ["-n", "realesr-animevideov3", "-s", "4", "-t", "192"])
        self.assertFalse(Path(args[5]).exists())
        self.assertEqual(list(self.root.glob("fidelis-preview-model.*")), [])

    def test_failure_status_and_temporary_cleanup(self):
        run = subprocess.run(self.command(), env=dict(self.env, FAKE_EXIT="7"), capture_output=True)
        self.assertEqual(run.returncode, 7)
        self.assertTrue(self.record.exists())
        self.assertEqual(list(self.root.glob("fidelis-preview-model.*")), [])

    def test_unsupported_model_scale_and_missing_value_never_execute(self):
        bad_model = self.runtime / "models-DF2K"
        bad_model.mkdir()
        for name in ("x4.param", "x4.bin"):
            (bad_model / name).write_bytes(b"unselected")
        invalid = [self.command()[:-1], self.command()[:-4] + ["-s", "2", "-t", "192"],
                   self.command()[:7] + [str(bad_model), "-s", "4", "-t", "192"],
                   ["bash", str(self.wrapper), "--unexpected"]]
        for command in invalid:
            with self.subTest(command=command):
                run = subprocess.run(command, env=self.env, capture_output=True)
                self.assertEqual(run.returncode, 2)
                self.assertFalse(self.record.exists())


if __name__ == "__main__":
    unittest.main()
