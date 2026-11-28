"""Offline input validation, installation isolation and retained failure evidence."""

import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fidelis.studio.offline_environment import install_offline_environment


class OfflineEnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.app = self.root / "app"
        self.app.mkdir()
        self.wheels = self.root / "wheels"
        self.wheels.mkdir()
        self.wheel = self.wheels / "demo-1.0-py3-none-any.whl"
        self.wheel.write_bytes(b"fixture wheel; mocked pip only")
        self.digest = hashlib.sha256(self.wheel.read_bytes()).hexdigest()
        self.lock = self.root / "requirements.txt"
        self.lock.write_text(f"# test\ndemo==1.0 --hash=sha256:{self.digest}\n")

    def install(self):
        return install_offline_environment(self.app, wheelhouse=self.wheels,
                                           requirements_lock=self.lock, python_executable="existing-python")

    def completed(self, command, **kwargs):
        if command[-2] == "-c":
            return SimpleNamespace(returncode=0, stdout=json.dumps({
                "python_executable": str(self.app / ".venv/bin/python"),
                "python_version": "fixture", "installed_versions": {"demo": "1.0"},
            }))
        return SimpleNamespace(returncode=0, stdout="fixture subprocess output\n")

    def test_ready_receipt_requires_all_stages_and_offline_flags(self):
        with patch("subprocess.run", side_effect=self.completed) as run:
            receipt = self.install()
        self.assertEqual(receipt["status"], "dependency_environment_ready")
        self.assertEqual(receipt["native_runtime_readiness"], "unverified")
        self.assertEqual(receipt["model_readiness"], "unverified")
        self.assertEqual(receipt["release_approval"], "not_granted")
        self.assertEqual(receipt["wheels"][0]["sha256"], self.digest)
        self.assertEqual(run.call_count, 3)
        command = run.call_args_list[1].args[0]
        for flag in ("-I", "--no-index", "--require-hashes", "--only-binary=:all:", "--no-cache-dir"):
            self.assertIn(flag, command)
        self.assertNotEqual(command[-1], str(self.lock))
        self.assertEqual(Path(command[-1]).read_text(), f"demo==1.0 --hash=sha256:{self.digest}\n")
        self.assertIn("skimage", run.call_args_list[2].args[0][-1])

    def test_reject_unsafe_or_unpinned_lock_before_creating_evidence(self):
        examples = ["demo", "demo>=1.0", "demo==1.0", "-r other.txt",
                    "--index-url https://example.test", "demo @ https://example.test/demo.whl",
                    f"demo==1.0;python_version>'3' --hash=sha256:{self.digest}",
                    f"demo==1.0 --hash=sha256:{self.digest} --extra-index-url=https://example.test"]
        for text in examples:
            with self.subTest(text=text), patch("subprocess.run") as run:
                self.lock.write_text(text)
                with self.assertRaises(ValueError):
                    self.install()
                run.assert_not_called()
                self.assertEqual(list(self.app.iterdir()), [])

    def test_empty_and_duplicate_normalized_locks_fail_closed(self):
        for text in ("# empty\n", f"Demo==1.0 --hash=sha256:{self.digest}\ndemo==1.0 --hash=sha256:{self.digest}"):
            with self.subTest(text=text):
                self.lock.write_text(text)
                with self.assertRaises(ValueError):
                    self.install()

    def test_missing_tampered_or_unexpected_wheels_fail_before_install(self):
        self.wheel.write_bytes(b"tampered")
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            self.install()
        self.wheel.unlink()
        with self.assertRaisesRegex(ValueError, "Missing"):
            self.install()
        (self.wheels / "other-1.0-py3-none-any.whl").write_bytes(b"unlisted")
        with self.assertRaisesRegex(ValueError, "Unexpected"):
            self.install()
        self.assertEqual(list(self.app.iterdir()), [])

    def test_wheel_symlink_and_remote_link_page_are_rejected(self):
        external = self.root / "external.whl"
        self.wheel.rename(external)
        self.wheel.symlink_to(external)
        with self.assertRaisesRegex(ValueError, "unsafe"):
            self.install()
        self.wheel.unlink()
        external.rename(self.wheel)
        (self.wheels / "index.html").write_text('<a href="https://example.test/evil.whl">remote</a>')
        with self.assertRaisesRegex(ValueError, "unsafe"):
            self.install()

    def test_existing_env_or_evidence_is_never_overwritten(self):
        for name in (".venv", "offline-python-install.json", "offline-python-install.log",
                     "offline-python-validated-lock.txt"):
            with self.subTest(name=name):
                existing = self.app / name
                existing.write_bytes(b"owner data")
                with self.assertRaises(FileExistsError):
                    self.install()
                self.assertEqual(existing.read_bytes(), b"owner data")
                existing.unlink()
        (self.app / ".venv").symlink_to(self.root / "absent")
        with self.assertRaises(FileExistsError):
            self.install()

    def test_pip_redirection_and_python_env_are_ignored(self):
        inherited = {"PIP_TARGET": "/unrelated", "PIP_PREFIX": "/unrelated", "PIP_INDEX_URL": "https://example.test",
                     "PIP_CONFIG_FILE": "/private/config", "PYTHONPATH": "/other", "PYTHONHOME": "/other"}
        with patch.dict(os.environ, inherited), patch("subprocess.run", side_effect=self.completed) as run:
            self.install()
        env = run.call_args_list[1].kwargs["env"]
        for name in inherited:
            if name != "PIP_CONFIG_FILE":
                self.assertNotIn(name, env)
        self.assertEqual(env["PIP_CONFIG_FILE"], os.devnull)

    def test_install_failure_preserves_log_lock_and_failed_receipt(self):
        failure = SimpleNamespace(returncode=1, stdout="fixture pip refused incompatible wheel\n")
        with patch("subprocess.run", side_effect=[self.completed(["venv", "command"]), failure]):
            with self.assertRaises(RuntimeError):
                self.install()
        receipt = json.loads((self.app / "offline-python-install.json").read_text())
        self.assertEqual(receipt["status"], "failed")
        self.assertIn("failed", receipt["error"])
        self.assertTrue((self.app / ".venv").is_dir())
        self.assertIn("incompatible", (self.app / "offline-python-install.log").read_text())
        with self.assertRaises(FileExistsError):
            self.install()

    def test_import_failure_or_wrong_installed_version_cannot_claim_success(self):
        with patch("subprocess.run", side_effect=[self.completed(["venv", "command"]),
                   self.completed(["pip", "command"]), SimpleNamespace(returncode=1, stdout="import failed")]):
            with self.assertRaises(RuntimeError):
                self.install()
        self.assertEqual(json.loads((self.app / "offline-python-install.json").read_text())["status"], "failed")

    def test_timeout_is_wrapped_and_retained(self):
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("venv", 300)):
            with self.assertRaises(RuntimeError):
                self.install()
        self.assertEqual(json.loads((self.app / "offline-python-install.json").read_text())["status"], "failed")


if __name__ == "__main__":
    unittest.main()
