"""Hybrid zero-cost texture backend: ComfyUI GPU -> M1 RealeSR-general-v3 -> CPU fallback."""
from __future__ import annotations

import hashlib
import importlib.util
import os
import platform
import subprocess  # nosec B404
import tempfile
from pathlib import Path
from typing import Any, Callable

import numpy as np
from PIL import Image

from fidelis.engine.restoration_runner import DimensionMismatchError
from fidelis.engine.tiler import MultiDiffusionTiler
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


def _load_candidate_entry(
    model_id: str, catalog_path: Path = CATALOG_PATH
) -> tuple[str, tuple[str, str]] | None:
    if not catalog_path.is_file():
        return None
    for line in catalog_path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) >= 6 and parts[0].strip() == model_id:
            folder = parts[3].strip()
            return folder, (parts[4].strip().lower(), parts[5].strip().lower())
    return None


def _load_expected_hashes(
    catalog_path: Path = CATALOG_PATH, model_id: str = MODEL_NAME
) -> tuple[str, str] | None:
    entry = _load_candidate_entry(model_id, catalog_path=catalog_path)
    return entry[1] if entry is not None else None


def _default_app_home() -> Path:
    return Path(os.environ.get("FIDELIS_HOME", Path.home() / ".local" / "share" / "fidelis"))


def detect_local_compute_capabilities(app_home: str | Path | None = None) -> dict[str, Any]:
    """Inventory zero-cost local compute options (NCNN-Vulkan, Apple MPS, ONNX, CPU)."""
    home = Path(app_home) if app_home is not None else _default_app_home()
    env_engine = os.environ.get("FIDELIS_ENGINE")
    engine_path = Path(env_engine) if env_engine else home / "runtime" / "realsr-ncnn"
    model_dir = home / "runtime" / f"models-{MODEL_NAME}"
    ncnn_ready = (
        engine_path.is_file()
        and os.access(engine_path, os.X_OK)
        and (model_dir / "x4.param").is_file()
        and (model_dir / "x4.bin").is_file()
    )
    torch_spec = importlib.util.find_spec("torch")
    mps_available = False
    if torch_spec is not None:
        import torch  # pragma: no cover

        mps_available = bool(torch.backends.mps.is_available())
    onnx_available = importlib.util.find_spec("onnxruntime") is not None
    return {
        "system": platform.system(),
        "machine": platform.machine(),
        "ncnn_vulkan_available": ncnn_ready,
        "mps_available": mps_available,
        "onnxruntime_available": onnx_available,
        "cpu_fallback_available": True,
        "allow_remote_cloud_fallback": False,
    }


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


class LocalCPUFallbackBackend:
    """Zero-cost CPU Lanczos-3 + restrained luminance detail fallback (no network/GPU)."""

    backend_name = "cpu_lanczos_fallback"
    model_id = "lanczos3-cpu"
    weights_sha256 = "deterministic_lanczos3_cpu"

    def restore(
        self,
        source_rgb: np.ndarray,
        *,
        base_4x: np.ndarray,
        scale: int,
        target_shape: tuple[int, int, int],
        case_id: str | None = None,
    ) -> tuple[np.ndarray, dict[str, Any]]:
        """Produce a clean Lanczos-3 base when neither GPU nor NCNN runtime is present."""
        del base_4x, scale, case_id
        target_h, target_w = int(target_shape[0]), int(target_shape[1])
        img = Image.fromarray(np.asarray(source_rgb, dtype=np.uint8))
        out = np.asarray(img.resize((target_w, target_h), Image.Resampling.LANCZOS), dtype=np.uint8)
        return out, {
            "backend": self.backend_name,
            "model": "lanczos3-cpu",
            "api_fee_usd": 0.0,
            "cloud_fallback": False,
            "evidence_level": "E1_cpu_fallback",
        }


class RealESRGANNCNNBackend:
    """Zero-cost local NCNN-Vulkan RealeSR-general-v3 backend (Apple M1 / Android)."""

    backend_name = "realesrgan_ncnn_vulkan"

    def __init__(
        self,
        *,
        app_home: str | Path | None = None,
        engine_path: str | Path | None = None,
        model_dir: str | Path | None = None,
        model_id: str = MODEL_NAME,
        verify_hashes: bool = True,
        tile_threshold: int = 512,
        detail_blend_weight: float = 1.0,
        command_runner: Callable[[list[str]], subprocess.CompletedProcess[str]] | None = None,
    ) -> None:
        if not 0.0 < float(detail_blend_weight) <= 1.0:
            raise ValueError("detail_blend_weight must be in (0.0, 1.0]")
        home = Path(app_home) if app_home is not None else _default_app_home()
        env_engine = os.environ.get("FIDELIS_ENGINE")
        self.engine_path = Path(engine_path) if engine_path is not None else (
            Path(env_engine) if env_engine else home / "runtime" / "realsr-ncnn"
        )
        self.model_id = str(model_id)
        candidate_entry = _load_candidate_entry(self.model_id)
        default_folder = candidate_entry[0] if candidate_entry is not None else f"models-{self.model_id}"
        self.model_dir = Path(model_dir) if model_dir is not None else home / "runtime" / default_folder
        self._custom_model_dir = model_dir is not None
        self.verify_hashes = verify_hashes
        self.tile_threshold = int(tile_threshold)
        self.detail_blend_weight = float(detail_blend_weight)
        self._command_runner = command_runner
        self._verified_hashes: tuple[str, str] | None = None

    @property
    def weights_sha256(self) -> str:
        """Return verified binary SHA-256 after readiness check, or unverified sentinel."""
        if self._verified_hashes is not None:
            return self._verified_hashes[1]
        return "unverified_until_run"

    def _ensure_ready(self) -> tuple[str, str]:
        if not self.engine_path.is_file() or not os.access(self.engine_path, os.X_OK):
            raise BackendUnavailable(f"Local NCNN runtime not installed: {self.engine_path}")
        param_path = self.model_dir / "x4.param"
        bin_path = self.model_dir / "x4.bin"
        if not param_path.is_file() or not bin_path.is_file():
            raise BackendUnavailable(f"Local {self.model_id} weights missing in {self.model_dir}")
        param_sha = _sha256_file(param_path)
        bin_sha = _sha256_file(bin_path)
        if self.verify_hashes:
            expected = _load_expected_hashes(model_id=self.model_id)
            if expected is not None and (param_sha, bin_sha) != expected:
                raise BackendUnavailable(f"{self.model_id} weight digest mismatch in {self.model_dir}")
        self._verified_hashes = (param_sha, bin_sha)
        return self._verified_hashes

    def _run_ncnn(self, src_path: Path, dst_path: Path) -> None:
        cli_path = REPO_ROOT / "bin" / "fidelis"
        if self._command_runner is not None:
            cmd = [
                str(self.engine_path),
                "-i", str(src_path),
                "-o", str(dst_path),
                "-m", str(self.model_dir),
                "-n", "realesr-general-v3",
                "-s", "4",
            ]
            proc = self._command_runner(cmd)
        elif (
            not self._custom_model_dir
            and cli_path.is_file()
            and os.access(cli_path, os.X_OK)
            and self.model_dir.name.startswith("models-")
        ):
            cli_selector = self.model_dir.name[len("models-"):]
            cmd = [str(cli_path), "upscale", str(src_path), str(dst_path), "--model", cli_selector]
            proc = subprocess.run(cmd, capture_output=True, text=True, check=False)  # nosec B603
        else:
            cmd = [
                str(self.engine_path),
                "-i", str(src_path),
                "-o", str(dst_path),
                "-m", str(self.model_dir),
                "-s", "4",
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True, check=False)  # nosec B603
        if proc.returncode != 0 or not dst_path.is_file():
            detail = (proc.stderr or proc.stdout or "").strip()
            raise BackendUnavailable(f"{self.model_id} execution failed ({proc.returncode}): {detail}")

    def _upscale_single(self, arr_rgb: np.ndarray) -> np.ndarray:
        with tempfile.TemporaryDirectory(prefix="fidelis-realesr-") as tmpdir:
            src_path = Path(tmpdir) / "source.png"
            dst_path = Path(tmpdir) / "output.png"
            Image.fromarray(np.asarray(arr_rgb, dtype=np.uint8)).save(src_path)
            self._run_ncnn(src_path, dst_path)
            with Image.open(dst_path) as img:
                return np.asarray(img.convert("RGB"), dtype=np.uint8)

    def restore(
        self,
        source_rgb: np.ndarray,
        *,
        base_4x: np.ndarray,
        scale: int,
        target_shape: tuple[int, int, int],
        case_id: str | None = None,
    ) -> tuple[np.ndarray, dict[str, Any]]:
        """Run local zero-cost RealeSR-general-v3 with automatic tiling for large inputs."""
        del case_id
        if int(scale) != 4:
            raise ValueError(f"{self.model_id} only supports fixed 4x scaling, got scale={scale}")
        param_sha, bin_sha = self._ensure_ready()
        src = np.asarray(source_rgb, dtype=np.uint8)
        h, w = src.shape[:2]
        tiled = max(h, w) > self.tile_threshold
        if tiled:
            tiler = MultiDiffusionTiler(tile_size=1024, overlap=128, scale=4, weight_type="cosine")
            raw_out = tiler.process(src, self._upscale_single)
        else:
            raw_out = self._upscale_single(src)

        target_h, target_w = int(target_shape[0]), int(target_shape[1])
        expected_shape = (target_h, target_w, 3)
        if raw_out.shape != expected_shape:
            raise DimensionMismatchError(
                f"{self.model_id} output shape {raw_out.shape} does not match expected "
                f"{expected_shape}; silent resizing is forbidden"
            )
        out = raw_out
        if self.detail_blend_weight < 1.0:
            base_arr = np.asarray(base_4x, dtype=np.float32)
            if base_arr.shape != out.shape:
                raise DimensionMismatchError(
                    f"Precision base shape {base_arr.shape} does not match {out.shape}; "
                    "silent resizing is forbidden"
                )
            w_det = self.detail_blend_weight
            out = np.clip(
                np.rint(w_det * out.astype(np.float32) + (1.0 - w_det) * base_arr),
                0,
                255,
            ).astype(np.uint8)
        return out, {
            "backend": self.backend_name,
            "model": self.model_id,
            "tiled": tiled,
            "detail_blend_weight": self.detail_blend_weight,
            "param_sha256": param_sha,
            "bin_sha256": bin_sha,
            "weights_sha256": bin_sha,
            "api_fee_usd": 0.0,
            "cloud_fallback": False,
            "evidence_level": "E2_local_m1_ncnn",
        }


class HybridTextureBackend:
    """Select ComfyUI GPU -> M1 RealeSR-general-v3 -> CPU fallback at zero paid cost."""

    backend_name = "hybrid_zero_cost_texture"

    def __init__(
        self,
        *,
        comfy_backend: Any | None = None,
        realesr_backend: RealESRGANNCNNBackend | None = None,
        cpu_backend: LocalCPUFallbackBackend | None = None,
        address: str = "http://127.0.0.1:8188",
        probe_timeout: float = 1.5,
        probe_fn: Callable[[], dict[str, Any]] | None = None,
        model_id: str | None = None,
    ) -> None:
        self.comfy_backend = comfy_backend
        self.realesr_backend = realesr_backend or RealESRGANNCNNBackend()
        self.cpu_backend = cpu_backend or LocalCPUFallbackBackend()
        self.address = address
        self.probe_timeout = probe_timeout
        self.probe_fn = probe_fn
        self._configured_model_id = model_id
        self._last_model_id: str | None = None
        self._last_weights_sha256: str = "unresolved_until_run"

    @property
    def model_id(self) -> str:
        """Return configured or last-selected model identifier."""
        if self._configured_model_id:
            return self._configured_model_id
        if self._last_model_id:
            return self._last_model_id
        return f"hybrid({getattr(self.realesr_backend, 'model_id', MODEL_NAME)})"

    @property
    def weights_sha256(self) -> str:
        """Return SHA-256 provenance of the backend selected in the latest run."""
        return self._last_weights_sha256

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
        """Run ComfyUI if reachable, else M1 RealeSR-general-v3, else CPU fallback."""
        status = self.detect_worker()
        if status["selected_backend"] == "comfyui" and self.comfy_backend is not None:
            try:
                out, meta = self.comfy_backend.restore(
                    source_rgb, base_4x=base_4x, scale=scale, target_shape=target_shape, case_id=case_id
                )
                self._last_model_id = str(getattr(self.comfy_backend, "model_id", "comfyui"))
                self._last_weights_sha256 = str(
                    meta.get("weights_sha256")
                    or getattr(self.comfy_backend, "weights_sha256", "unavailable_unverified")
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

        try:
            out, meta = self.realesr_backend.restore(
                source_rgb, base_4x=base_4x, scale=scale, target_shape=target_shape, case_id=case_id
            )
            self._last_model_id = str(meta.get("model") or getattr(self.realesr_backend, "model_id", MODEL_NAME))
            self._last_weights_sha256 = str(meta.get("bin_sha256") or self.realesr_backend.weights_sha256)
            return out, {
                **meta,
                "backend_selected": self.realesr_backend.backend_name,
                "fallback_used": True,
                "fallback_reason": status.get("fallback_reason", "comfyui_unreachable"),
                "gpu_milestone_verified": False,
                "api_fee_usd": 0.0,
                "cloud_fallback": False,
            }
        except (BackendUnavailable, OSError) as exc:
            out, meta = self.cpu_backend.restore(
                source_rgb, base_4x=base_4x, scale=scale, target_shape=target_shape, case_id=case_id
            )
            self._last_model_id = str(meta.get("model") or getattr(self.cpu_backend, "model_id", "lanczos3-cpu"))
            self._last_weights_sha256 = str(
                getattr(self.cpu_backend, "weights_sha256", "deterministic_lanczos3_cpu")
            )
            return out, {
                **meta,
                "backend_selected": self.cpu_backend.backend_name,
                "fallback_used": True,
                "fallback_reason": f"{status.get('fallback_reason', 'comfyui_unreachable')}+ncnn:{type(exc).__name__}",
                "gpu_milestone_verified": False,
                "api_fee_usd": 0.0,
                "cloud_fallback": False,
            }
