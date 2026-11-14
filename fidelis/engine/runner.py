"""Facade and convenience runners for Fidelis restoration engine."""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any, Callable, Optional

import numpy as np
from PIL import Image, UnidentifiedImageError

from fidelis.engine.restoration_runner import (
    BackendUnavailableError,
    BicubicBaselineBackend,
    ComfyRestorationBackend,
    DimensionMismatchError,
    ImportedRestorationBackend,
    OnnxRestorationBackend,
    RestorationBackend,
    RestorationProvenance,
    RestorationResult,
    RestorationRunner,
    TorchSpandrelRestorationBackend,
    _enforce_exact_shape,
    _sha256_file,
    _validate_rgb_uint8,
    create_restoration_runner,
)


class ImportedRestorationRunner:
    """Convenience runner loading an exact-grid 4x imported RGB image with provenance."""

    def __init__(self, model_id: str = "imported") -> None:
        self.model_id = str(model_id)

    def run(
        self,
        source_rgb: np.ndarray,
        *,
        imported_path: str | Path,
        scale: int = 4,
    ) -> tuple[np.ndarray, dict[str, Any]]:
        src = _validate_rgb_uint8(source_rgb, "source_rgb")
        if int(scale) < 1:
            raise ValueError(f"scale must be >= 1, got {scale}")
        path = Path(imported_path)
        if not path.is_file():
            raise FileNotFoundError(f"Imported restoration image not found: {path}")

        try:
            with Image.open(path) as img:
                if img.mode != "RGB":
                    raise ValueError(
                        f"Imported image {path.name} must be 3-channel RGB, got mode {img.mode!r}"
                    )
                arr = np.asarray(img, dtype=np.uint8)
        except UnidentifiedImageError as exc:
            raise ValueError(f"Corrupted or unreadable image file {path}: {exc}") from exc

        sh, sw, _ = src.shape
        target_shape = (sh * int(scale), sw * int(scale), 3)
        out = _enforce_exact_shape(arr, target_shape, f"imported({path.name})")

        provenance = {
            "model_id": self.model_id,
            "backend": "imported",
            "weights_sha256": "imported",
            "output_sha256": _sha256_file(path),
            "imported_path": str(path),
            "scale": int(scale),
            "source_shape": [int(sh), int(sw), 3],
            "target_shape": [int(target_shape[0]), int(target_shape[1]), 3],
        }
        return out, provenance


class CallableRestorationRunner:
    """Convenience runner wrapping a user-supplied callable fn(source_rgb, scale) -> output_rgb."""

    def __init__(
        self,
        model_id: str,
        fn: Callable[[np.ndarray, int], np.ndarray],
        *,
        backend_name: str = "callable",
    ) -> None:
        if not callable(fn):
            raise TypeError("fn must be callable")
        self.model_id = str(model_id)
        self.fn = fn
        self.backend_name = str(backend_name)

    def run(
        self,
        source_rgb: np.ndarray,
        scale: int = 4,
    ) -> tuple[np.ndarray, dict[str, Any]]:
        src = _validate_rgb_uint8(source_rgb, "source_rgb")
        if int(scale) < 1:
            raise ValueError(f"scale must be >= 1, got {scale}")
        sh, sw, _ = src.shape
        target_shape = (sh * int(scale), sw * int(scale), 3)

        raw = self.fn(src, int(scale))
        out = _enforce_exact_shape(raw, target_shape, "callable_output")

        provenance = {
            "model_id": self.model_id,
            "backend": self.backend_name,
            "weights_sha256": "callable",
            "scale": int(scale),
            "source_shape": [int(sh), int(sw), 3],
            "target_shape": [int(target_shape[0]), int(target_shape[1]), 3],
        }
        return out, provenance


def _probe_module(name: str) -> tuple[bool, Optional[str]]:
    try:
        mod = importlib.import_module(name)
        return True, getattr(mod, "__version__", None)
    except Exception as exc:
        return False, str(exc)


def list_available_backends() -> dict[str, dict[str, Any]]:
    """Report available restoration backends without raising on missing optional runtimes."""
    ort_ok, ort_info = _probe_module("onnxruntime")
    torch_ok, torch_info = _probe_module("torch")
    spandrel_ok, spandrel_info = _probe_module("spandrel")
    return {
        "imported": {"available": True, "reason": None},
        "bicubic": {"available": True, "reason": None},
        "comfyui": {"available": True, "reason": "requires running ComfyUI server"},
        "onnxruntime": {
            "available": ort_ok,
            "version": ort_info if ort_ok else None,
            "reason": None if ort_ok else ort_info,
        },
        "torch_spandrel": {
            "available": bool(torch_ok and spandrel_ok),
            "torch_available": torch_ok,
            "spandrel_available": spandrel_ok,
            "reason": None if (torch_ok and spandrel_ok) else (torch_info if not torch_ok else spandrel_info),
        },
    }


__all__ = [
    "BackendUnavailableError",
    "BicubicBaselineBackend",
    "CallableRestorationRunner",
    "ComfyRestorationBackend",
    "DimensionMismatchError",
    "ImportedRestorationBackend",
    "ImportedRestorationRunner",
    "OnnxRestorationBackend",
    "RestorationBackend",
    "RestorationProvenance",
    "RestorationResult",
    "RestorationRunner",
    "TorchSpandrelRestorationBackend",
    "create_restoration_runner",
    "list_available_backends",
]
