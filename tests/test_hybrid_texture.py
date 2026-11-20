"""Tests for automatic ComfyUI worker detection and zero-cost RealeSR-general-v3 fallback."""
from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from fidelis.studio.comfy import BackendUnavailable
from fidelis.studio.hybrid_texture import (
    HybridTextureBackend,
    RealESRGANNCNNBackend,
    probe_comfy_worker,
)


class _StubComfyBackend:
    def __init__(self, *, fail_with: Exception | None = None) -> None:
        self.fail_with = fail_with
        self.calls = 0

    def restore(self, source_rgb, *, base_4x, scale, target_shape, case_id=None):
        del source_rgb, scale, case_id
        self.calls += 1
        if self.fail_with is not None:
            raise self.fail_with
        return np.full(target_shape, 42, dtype=np.uint8), {"comfy_run_id": "stub-1"}


def _make_fake_realesr_env(tmp_path: Path) -> tuple[Path, Path]:
    engine = tmp_path / "realsr-ncnn"
    engine.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    engine.chmod(0o755)
    model_dir = tmp_path / "models-RealeSR-general-v3"
    model_dir.mkdir(parents=True, exist_ok=True)
    (model_dir / "x4.param").write_bytes(b"param")
    (model_dir / "x4.bin").write_bytes(b"bin")
    return engine, model_dir


def _fake_runner_factory(value: int = 123):
    def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        out_path = Path(cmd[cmd.index("-o") + 1])
        src_path = Path(cmd[cmd.index("-i") + 1])
        with Image.open(src_path) as src:
            w, h = src.size
        Image.fromarray(np.full((h * 4, w * 4, 3), value, dtype=np.uint8), mode="RGB").save(out_path)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    return _run


class HybridTextureBackendTests(unittest.TestCase):
    def test_probe_comfy_worker_offline_returns_unreachable_no_cloud(self) -> None:
        result = probe_comfy_worker("http://127.0.0.1:1", timeout=0.2)
        self.assertFalse(result["reachable"])
        self.assertFalse(result["allow_remote_cloud_fallback"])

    def test_falls_back_to_realesr_when_comfy_unreachable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            engine, model_dir = _make_fake_realesr_env(Path(tmp))
            realesr = RealESRGANNCNNBackend(
                engine_path=engine,
                model_dir=model_dir,
                verify_hashes=False,
                command_runner=_fake_runner_factory(111),
            )
            comfy = _StubComfyBackend()
            hybrid = HybridTextureBackend(
                comfy_backend=comfy,
                realesr_backend=realesr,
                probe_fn=lambda: {"reachable": False, "reason": "ConnectionError"},
            )
            src = np.zeros((8, 8, 3), dtype=np.uint8)
            base_4x = np.zeros((32, 32, 3), dtype=np.uint8)
            out, meta = hybrid.restore(src, base_4x=base_4x, scale=4, target_shape=(32, 32, 3))

            self.assertEqual(comfy.calls, 0)
            self.assertEqual(out.shape, (32, 32, 3))
            self.assertEqual(int(out[0, 0, 0]), 111)
            self.assertEqual(meta["backend_selected"], "realesrgan_ncnn_vulkan")
            self.assertTrue(meta["fallback_used"])
            self.assertEqual(meta["fallback_reason"], "comfyui_unreachable")
            self.assertFalse(meta["gpu_milestone_verified"])
            self.assertFalse(meta["cloud_fallback"])
            self.assertEqual(meta["api_fee_usd"], 0.0)

    def test_uses_comfy_when_reachable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            engine, model_dir = _make_fake_realesr_env(Path(tmp))
            realesr = RealESRGANNCNNBackend(
                engine_path=engine,
                model_dir=model_dir,
                verify_hashes=False,
                command_runner=_fake_runner_factory(111),
            )
            comfy = _StubComfyBackend()
            hybrid = HybridTextureBackend(
                comfy_backend=comfy,
                realesr_backend=realesr,
                probe_fn=lambda: {"reachable": True},
            )
            src = np.zeros((8, 8, 3), dtype=np.uint8)
            base_4x = np.zeros((32, 32, 3), dtype=np.uint8)
            out, meta = hybrid.restore(src, base_4x=base_4x, scale=4, target_shape=(32, 32, 3))

            self.assertEqual(comfy.calls, 1)
            self.assertEqual(int(out[0, 0, 0]), 42)
            self.assertEqual(meta["backend_selected"], "comfyui")
            self.assertFalse(meta["fallback_used"])
            self.assertTrue(meta["gpu_milestone_verified"])
            self.assertEqual(meta["api_fee_usd"], 0.0)

    def test_falls_back_when_comfy_raises_backend_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            engine, model_dir = _make_fake_realesr_env(Path(tmp))
            realesr = RealESRGANNCNNBackend(
                engine_path=engine,
                model_dir=model_dir,
                verify_hashes=False,
                command_runner=_fake_runner_factory(77),
            )
            comfy = _StubComfyBackend(fail_with=BackendUnavailable("offline mid-call"))
            hybrid = HybridTextureBackend(
                comfy_backend=comfy,
                realesr_backend=realesr,
                probe_fn=lambda: {"reachable": True},
            )
            src = np.zeros((8, 8, 3), dtype=np.uint8)
            base_4x = np.zeros((32, 32, 3), dtype=np.uint8)
            out, meta = hybrid.restore(src, base_4x=base_4x, scale=4, target_shape=(32, 32, 3))

            self.assertEqual(int(out[0, 0, 0]), 77)
            self.assertTrue(meta["fallback_used"])
            self.assertIn("BackendUnavailable", meta["fallback_reason"])
            self.assertFalse(meta["gpu_milestone_verified"])


if __name__ == "__main__":
    unittest.main()
