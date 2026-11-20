"""Hybrid zero-cost texture backend: ComfyUI GPU when available, Apple M1 RealeSR-general-v3 fallback."""
from __future__ import annotations

import hashlib
import os
import subprocess  # nosec B404
import tempfile
from pathlib import Path
from typing import Any, Callable

import numpy as np
from PIL import Image

from fidelis.studio.comfy import BackendUnavailable, ComfyTextureBackend

MODEL_NAME = "RealeSR-general-v3"
REPO_ROOT = Path(__file__).resolve().parents[2]
CATALOG_PATH = REPO_ROOT / "config" / "photo-candidates.tsv"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_expected_hashes(catalog_path: Path = CATALOG_PATH) -> tuple[str, str] | None:
    if not catalog_path.is_file():
        return None
    for line in catalog_path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) >= 6 and parts[0] == MODEL_NAME:
            return parts[4].strip().lower(), parts[5].strip().lower()
    return None


def _default_app_home() -> Path:
    return Path(os.environ.get("FIDELIS_HOME", Path.home() / ".local" / "share" / "fidelis"))


def probe_comfy_worker(
    address: str = "http://127.0.0.1:8188",
    *,
    timeout: float = 1.5,
    probe_fn: Callable[[], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Detect whether a local loopback ComfyUI worker is reachable without cloud fallback."""
    if probe_fn is not None:
        result = dict(probe_fn())
        result.setdefault("reachable", False)
        result["allow_remote_cloud_fallback"] = False
        return result
    with tempfile.TemporaryDirectory(prefix="fidelis-probe-") as tmpdir:
        backend = ComfyTextureBackend(tmpdir, address=address, timeout=timeout)
        try:
            result = backend.probe()
        finally:
            backend.close()
    result["allow_remote_cloud_fallback"] = False
    return result


class RealESRGANNCNNBackend:
    """Zero-cost local NCNN-Vulkan RealeSR-general-v3 backend (Apple M1 / Android)."""

    backend_name = "realesrgan_ncnn_vulkan"

    def __init__(
        self,
        *,
        app_home: str | Path | None = None,
        engine_path: str | Path | None = None,
        model_dir: str | Path | None = None,
        verify_hashes: bool = True,
        command_runner: Callable[[list[str]], subprocess.CompletedProcess[str]] | None = None,
    ) -> None:
        home = Path(app_home) if app_home is not None else _default_app_home()
        env_engine = os.environ.get("FIDELIS_ENGINE")
        self.engine_path = Path(engine_path) if engine_path is not None else (
            Path(env_engine) if env_engine else home / "runtime" / "realsr-ncnn"
        )
        self.model_dir = Path(model_dir) if model_dir is not None else home / "runtime" / f"models-{MODEL_NAME}"
        self.verify_hashes = verify_hashes
        self._command_runner = command_runner
        self._verified_hashes: tuple[str, str] | None = None

    def _ensure_ready(self) -> tuple[str, str]:
        if not self.engine_path.is_file() or not os.access(self.engine_path, os.X_OK):
            raise BackendUnavailable(f"Local NCNN runtime not installed: {self.engine_path}")
        param_path = self.model_dir / "x4.param"
        bin_path = self.model_dir / "x4.bin"
        if not param_path.is_file() or not bin_path.is_file():
            raise BackendUnavailable(f"Local {MODEL_NAME} weights missing in {self.model_dir}")
        param_sha = _sha256_file(param_path)
        bin_sha = _sha256_file(bin_path)
        if self.verify_hashes:
            expected = _load_expected_hashes()
            if expected is not None and (param_sha, bin_sha) != expected:
                raise BackendUnavailable(f"{MODEL_NAME} weight digest mismatch in {self.model_dir}")
        self._verified_hashes = (param_sha, bin_sha)
        return self._verified_hashes

    def _run_ncnn(self, src_path: Path, dst_path: Path) -> None:
        cmd = [
            str(self.engine_path),
            "-i", str(src_path),
            "-o", str(dst_path),
            "-m", str(self.model_dir),
            "-n", "realesr-general-v3",
            "-s", "4",
        ]
        if self._command_runner is not None:
            proc = self._command_runner(cmd)
        else:
            proc = subprocess.run(cmd, capture_output=True, text=True, check=False)  # nosec B603
        if proc.returncode != 0 or not dst_path.is_file():
            detail = (proc.stderr or proc.stdout or "").strip()
            raise BackendUnavailable(f"RealeSR-general-v3 execution failed ({proc.returncode}): {detail}")

    def restore(
        self,
        source_rgb: np.ndarray,
        *,
        base_4x: np.ndarray,
        scale: int,
        target_shape: tuple[int, int, int],
        case_id: str | None = None,
    ) -> tuple[np.ndarray, dict[str, Any]]:
        """Run local zero-cost RealeSR-general-v3 upscaling and conform to target_shape."""
        del base_4x, scale, case_id
        param_sha, bin_sha = self._ensure_ready()
        with tempfile.TemporaryDirectory(prefix="fidelis-realesr-") as tmpdir:
            src_path = Path(tmpdir) / "source.png"
            dst_path = Path(tmpdir) / "output.png"
            Image.fromarray(np.asarray(source_rgb, dtype=np.uint8), mode="RGB").save(src_path)
            self._run_ncnn(src_path, dst_path)
            with Image.open(dst_path) as img:
                rgb_img = img.convert("RGB")
                target_h, target_w = int(target_shape[0]), int(target_shape[1])
                if rgb_img.size != (target_w, target_h):
                    rgb_img = rgb_img.resize((target_w, target_h), Image.Resampling.LANCZOS)
                out = np.asarray(rgb_img, dtype=np.uint8)
        return out, {
            "backend": self.backend_name,
            "model": MODEL_NAME,
            "param_sha256": param_sha,
            "bin_sha256": bin_sha,
            "api_fee_usd": 0.0,
            "cloud_fallback": False,
            "evidence_level": "E2_local_m1_ncnn",
        }


class HybridTextureBackend:
    """Select ComfyUI GPU when reachable; gracefully fall back to local RealeSR-general-v3."""

    backend_name = "hybrid_zero_cost_texture"

    def __init__(
        self,
        *,
        comfy_backend: Any | None = None,
        realesr_backend: RealESRGANNCNNBackend | None = None,
        address: str = "http://127.0.0.1:8188",
        probe_timeout: float = 1.5,
        probe_fn: Callable[[], dict[str, Any]] | None = None,
    ) -> None:
        self.comfy_backend = comfy_backend
        self.realesr_backend = realesr_backend or RealESRGANNCNNBackend()
        self.address = address
        self.probe_timeout = probe_timeout
        self.probe_fn = probe_fn

    def detect_worker(self) -> dict[str, Any]:
        """Probe ComfyUI availability and report whether GPU or local fallback is active."""
        probe = probe_comfy_worker(self.address, timeout=self.probe_timeout, probe_fn=self.probe_fn)
        if probe.get("reachable") and self.comfy_backend is not None:
            return {
                "selected_backend": "comfyui",
                "comfy_reachable": True,
                "fallback_active": False,
                "allow_remote_cloud_fallback": False,
                "probe": probe,
            }
        reason = "comfyui_unreachable" if not probe.get("reachable") else "comfyui_backend_unconfigured"
        return {
            "selected_backend": self.realesr_backend.backend_name,
            "comfy_reachable": bool(probe.get("reachable")),
            "fallback_active": True,
            "fallback_reason": reason,
            "allow_remote_cloud_fallback": False,
            "probe": probe,
        }

    def restore(
        self,
        source_rgb: np.ndarray,
        *,
        base_4x: np.ndarray,
        scale: int,
        target_shape: tuple[int, int, int],
        case_id: str | None = None,
    ) -> tuple[np.ndarray, dict[str, Any]]:
        """Run ComfyUI if reachable, otherwise fall back to local RealeSR-general-v3."""
        status = self.detect_worker()
        if status["selected_backend"] == "comfyui" and self.comfy_backend is not None:
            try:
                out, meta = self.comfy_backend.restore(
                    source_rgb, base_4x=base_4x, scale=scale, target_shape=target_shape, case_id=case_id
                )
                return out, {
                    **meta,
                    "backend_selected": "comfyui",
                    "fallback_used": False,
                    "gpu_milestone_verified": True,
                    "api_fee_usd": 0.0,
                    "cloud_fallback": False,
                }
            except (BackendUnavailable, ConnectionError, OSError) as exc:
                status["fallback_reason"] = f"comfyui_runtime_unavailable:{type(exc).__name__}"

        out, meta = self.realesr_backend.restore(
            source_rgb, base_4x=base_4x, scale=scale, target_shape=target_shape, case_id=case_id
        )
        return out, {
            **meta,
            "backend_selected": self.realesr_backend.backend_name,
            "fallback_used": True,
            "fallback_reason": status.get("fallback_reason", "comfyui_unreachable"),
            "gpu_milestone_verified": False,
            "api_fee_usd": 0.0,
            "cloud_fallback": False,
        }
