"""Pluggable restoration model runner with strict 4x grid validation and texture guard."""

from __future__ import annotations

import hashlib
import importlib
import platform
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import (
    Any,
    Protocol,
    runtime_checkable,
)

import numpy as np
from PIL import Image

from fidelis.engine.checkpoints import CheckpointRestorationBackend
from fidelis.eval.comparators import ComparatorOutput
from fidelis.postprocess.regions import RegionBlend, compose_regions
from fidelis.postprocess.roi_protection import (
    VALID_POLICIES,
    VALID_ROI_KINDS,
    build_roi_protection_masks,
    screen_internal_drift,
)


class DimensionMismatchError(ValueError):
    """Raised on any dimension or channel mismatch; silent resizing is forbidden."""


class BackendUnavailableError(RuntimeError):
    """Raised when an optional restoration runtime (e.g. onnxruntime, torch, spandrel) is missing."""


@dataclass
class RestorationProvenance:
    """Provenance metadata for a single restoration run."""

    model_id: str
    backend: str
    weights_sha256: str
    scale: int
    source_shape: tuple[int, int, int]
    target_shape: tuple[int, int, int]
    texture_guard_applied: bool
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "backend": self.backend,
            "weights_sha256": self.weights_sha256,
            "scale": self.scale,
            "source_shape": list(self.source_shape),
            "target_shape": list(self.target_shape),
            "texture_guard_applied": self.texture_guard_applied,
            "extra": dict(self.extra),
        }


@dataclass
class RestorationResult:
    """Output bundle from RestorationRunner.run()."""

    image: np.ndarray
    raw_candidate: np.ndarray
    provenance: RestorationProvenance
    guard_receipt: dict[str, Any] | None
    drift_report: dict[str, Any] | None


@runtime_checkable
class RestorationBackend(Protocol):
    """Protocol implemented by all restoration backends."""

    model_id: str
    backend_name: str
    weights_sha256: str

    def restore(
        self,
        source_rgb: np.ndarray,
        *,
        base_4x: np.ndarray,
        scale: int,
        target_shape: tuple[int, int, int],
        case_id: str | None = None,
    ) -> tuple[np.ndarray, dict[str, Any]]:
        """Return (raw_candidate_rgb_uint8, extra_provenance_dict) on exact target_shape."""
        ...


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _validate_rgb_uint8(arr: np.ndarray, name: str) -> np.ndarray:
    if not isinstance(arr, np.ndarray):
        arr = np.asarray(arr)
    if arr.ndim != 3 or arr.shape[2] != 3:
        raise DimensionMismatchError(
            f"{name} must be 3D HxWx3 RGB, got shape {getattr(arr, 'shape', None)}"
        )
    if arr.dtype != np.uint8:
        raise ValueError(f"{name} must be uint8, got {arr.dtype}")
    if arr.shape[0] < 1 or arr.shape[1] < 1:
        raise DimensionMismatchError(f"{name} must have non-empty dimensions, got {arr.shape}")
    return arr


def _enforce_exact_shape(
    candidate: np.ndarray, target_shape: tuple[int, int, int], label: str = "candidate"
) -> np.ndarray:
    arr = _validate_rgb_uint8(candidate, label)
    if arr.shape != target_shape:
        raise DimensionMismatchError(
            f"{label} shape {arr.shape} does not match exact target shape {target_shape}; "
            "silent resizing is forbidden"
        )
    return arr


def _bicubic_upscale(source_rgb: np.ndarray, target_w: int, target_h: int) -> np.ndarray:
    return np.asarray(
        Image.fromarray(source_rgb).resize((target_w, target_h), Image.Resampling.BICUBIC),
        dtype=np.uint8,
    )


def _normalize_rois_for_guard(
    rois: Sequence[Mapping[str, Any]],
    source_shape: tuple[int, int],
    target_shape: tuple[int, int],
    roi_space: str = "target",
) -> list[dict[str, Any]]:
    if not rois:
        return []
    if roi_space not in ("target", "source", "auto"):
        raise ValueError(f"Unsupported roi_space {roi_space!r}")

    th, tw = target_shape
    sh, sw = source_shape
    scale_x = 1.0
    scale_y = 1.0
    if roi_space == "source" or (roi_space == "auto" and (tw != sw or th != sh)):
        scale_x = tw / float(sw)
        scale_y = th / float(sh)

    normalized: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for idx, entry in enumerate(rois):
        if not isinstance(entry, Mapping):
            raise TypeError("Each ROI entry must be a mapping")
        kind = str(entry.get("kind", "fabric"))
        if kind not in VALID_ROI_KINDS:
            raise ValueError(f"ROI {entry.get('id', idx)}: invalid kind {kind!r}")

        raw_policy = entry.get("policy")
        if raw_policy in VALID_POLICIES:
            policy = str(raw_policy)
        elif kind in ("hardware", "seam", "logo", "text", "identity", "alpha_boundary"):
            policy = "preserve"
        else:
            policy = "texture_allowed"

        override = entry.get("override")
        if override not in (None, "lock", "unlock"):
            raise ValueError(f"ROI {entry.get('id', idx)}: invalid override {override!r}")

        if "rect" in entry and isinstance(entry["rect"], (list, tuple)) and len(entry["rect"]) == 4:
            rx, ry, rw, rh = [float(v) for v in entry["rect"]]
        elif "bbox" in entry and isinstance(entry["bbox"], (list, tuple)) and len(entry["bbox"]) == 4:
            x0, y0, x1, y1 = [float(v) for v in entry["bbox"]]
            rx, ry, rw, rh = x0, y0, max(1.0, x1 - x0), max(1.0, y1 - y0)
        else:
            raise ValueError(f"ROI {entry.get('id', idx)} must specify 'rect' or 'bbox'")

        tx = max(0, min(tw - 1, round(rx * scale_x)))
        ty = max(0, min(th - 1, round(ry * scale_y)))
        tw_r = max(1, min(tw - tx, round(rw * scale_x)))
        th_r = max(1, min(th - ty, round(rh * scale_y)))

        rid = str(entry.get("id") or f"roi_{idx}").strip() or f"roi_{idx}"
        while rid in seen_ids:
            rid = f"{rid}_{idx}"
        seen_ids.add(rid)

        normalized.append(
            {
                "id": rid,
                "kind": kind,
                "policy": policy,
                "override": override,
                "rect": [tx, ty, tw_r, th_r],
                "label": str(entry.get("label", rid)),
            }
        )
    return normalized


class BicubicBaselineBackend:
    """Deterministic 4x PIL BICUBIC baseline backend."""

    backend_name = "bicubic"
    weights_sha256 = "deterministic_bicubic"

    def __init__(self, model_id: str = "bicubic_4x") -> None:
        self.model_id = model_id

    def restore(
        self,
        source_rgb: np.ndarray,
        *,
        base_4x: np.ndarray,
        scale: int,
        target_shape: tuple[int, int, int],
        case_id: str | None = None,
    ) -> tuple[np.ndarray, dict[str, Any]]:
        out = _enforce_exact_shape(base_4x.copy(), target_shape, "bicubic_4x")
        return out, {"resampling": "BICUBIC"}


class ImportedRestorationBackend:
    """Loads pre-rendered exact-grid 4x PNG/image outputs without resizing."""

    backend_name = "imported"
    weights_sha256 = "imported"

    def __init__(
        self,
        imported_dir: str | Path | None = None,
        *,
        file_map: Mapping[str, str | Path] | None = None,
        image_path: str | Path | None = None,
        model_id: str = "imported",
    ) -> None:
        self.imported_dir = Path(imported_dir) if imported_dir is not None else None
        self.file_map = {str(k): Path(v) for k, v in (file_map or {}).items()}
        self.image_path = Path(image_path) if image_path is not None else None
        self.model_id = model_id
        if self.imported_dir is None and not self.file_map and self.image_path is None:
            raise ValueError(
                "ImportedRestorationBackend requires imported_dir, file_map, or image_path"
            )

    def _resolve_path(self, case_id: str | None) -> Path:
        if case_id and case_id in self.file_map:
            p = self.file_map[case_id]
            if not p.is_file():
                raise FileNotFoundError(f"Imported image not found for case {case_id!r}: {p}")
            return p
        if self.imported_dir is not None and case_id:
            for ext in (".png", ".tif", ".tiff", ".webp", ".jpg"):
                candidate = self.imported_dir / f"{case_id}{ext}"
                if candidate.is_file():
                    return candidate
            raise FileNotFoundError(
                f"No imported output found for case {case_id!r} in {self.imported_dir}"
            )
        if self.image_path is not None:
            if not self.image_path.is_file():
                raise FileNotFoundError(f"Imported image not found: {self.image_path}")
            return self.image_path
        raise ValueError(
            "Cannot resolve imported image path without case_id or explicit image_path"
        )

    def restore(
        self,
        source_rgb: np.ndarray,
        *,
        base_4x: np.ndarray,
        scale: int,
        target_shape: tuple[int, int, int],
        case_id: str | None = None,
    ) -> tuple[np.ndarray, dict[str, Any]]:
        path = self._resolve_path(case_id)
        with Image.open(path) as img:
            if img.mode != "RGB":
                raise ValueError(
                    f"Imported image {path.name} must be 3-channel RGB, got mode {img.mode!r}"
                )
            # This runner composes in a defined sRGB working space. Pillow's
            # RGB conversion exposes encoded samples without applying an ICC
            # transform, so accepting a profiled or non-sRGB-tagged PNG here
            # would silently blend and export the wrong colours.
            if img.info.get("icc_profile"):
                raise ValueError(
                    f"Imported image {path.name} carries an ICC profile; convert it to untagged sRGB first"
                )
            if "transparency" in img.info:
                raise ValueError(
                    f"Imported image {path.name} has colour-key transparency; use explicit RGB samples"
                )
            if "srgb" not in img.info and (
                "gamma" in img.info or "chromaticity" in img.info
            ):
                raise ValueError(
                    f"Imported image {path.name} has non-sRGB PNG colour tags; convert it to sRGB first"
                )
            arr = np.asarray(img, dtype=np.uint8)
        out = _enforce_exact_shape(arr, target_shape, f"imported({path.name})")
        return out, {"imported_path": str(path), "imported_sha256": _sha256_file(path)}


class ComfyRestorationBackend:
    """Wraps ComfyTextureBackend, feeding the 4x bicubic canvas for 1:1 refinement."""

    backend_name = "comfyui"

    def __init__(
        self,
        bundle: dict[str, Any],
        *,
        comfy_backend: Any | None = None,
        root: str | Path | None = None,
        address: str = "http://127.0.0.1:8188",
        model_id: str = "comfyui",
        deadline_seconds: float = 300.0,
    ) -> None:
        if comfy_backend is None:
            if root is None:
                raise ValueError("ComfyRestorationBackend requires comfy_backend or root")
            # The local Comfy transport depends on optional HTTP packages.  Keep
            # those packages out of the offline-engine import path; they are
            # required only when this backend is explicitly selected.
            from fidelis.studio.comfy import ComfyTextureBackend
            comfy_backend = ComfyTextureBackend(root, address=address)
        self.comfy = comfy_backend
        self.bundle = bundle
        self.model_id = model_id
        self.deadline_seconds = float(deadline_seconds)
        # A graph digest does not attest to model checkpoint bytes. Keep the
        # workflow identity separate and mark weight provenance unavailable
        # until a real checkpoint hash has been independently verified.
        from fidelis.studio.comfy import canonical_hash
        self.workflow_sha256 = canonical_hash(bundle)
        checkpoint_hash = (
            bundle.get("checkpoint_sha256")
            or bundle.get("weights_sha256")
            or bundle.get("checkpoint_hash")
        )
        self.weights_sha256 = str(checkpoint_hash) if checkpoint_hash else "unavailable_unverified"

    def restore(
        self,
        source_rgb: np.ndarray,
        *,
        base_4x: np.ndarray,
        scale: int,
        target_shape: tuple[int, int, int],
        case_id: str | None = None,
    ) -> tuple[np.ndarray, dict[str, Any]]:
        canvas = _enforce_exact_shape(base_4x, target_shape, "comfy_input_canvas")
        run_id = self.comfy.default_cli_run_id(canvas, self.bundle, self.comfy.address)
        out_rgb, record = self.comfy.run(
            canvas,
            self.bundle,
            run_id=run_id,
            deadline_seconds=self.deadline_seconds,
        )
        out = _enforce_exact_shape(out_rgb, target_shape, "comfyui_output")
        return out, {
            "comfy_run_id": record.get("id", run_id),
            "workflow_sha256": record.get("workflow_sha256", self.workflow_sha256),
            "weights_sha256": self.weights_sha256,
            "family": record.get("family", self.bundle.get("family")),
        }


class OnnxRestorationBackend:
    """ONNX Runtime restoration backend with lazy import and SHA-256 weight provenance."""

    backend_name = "onnxruntime"

    def __init__(
        self,
        weights_path: str | Path,
        *,
        model_id: str | None = None,
        providers: Sequence[str] | None = None,
        session: Any = None,
    ) -> None:
        self.weights_path = Path(weights_path)
        if not self.weights_path.is_file():
            raise FileNotFoundError(f"ONNX model file not found: {self.weights_path}")
        self.model_id = model_id or self.weights_path.stem
        self.weights_sha256 = _sha256_file(self.weights_path)
        self.providers = list(providers) if providers is not None else ["CPUExecutionProvider"]

        if session is not None:
            self._session = session
        else:
            try:
                ort = importlib.import_module("onnxruntime")
            except ModuleNotFoundError as exc:
                raise BackendUnavailableError(
                    "onnxruntime is not installed in this environment"
                ) from exc
            self._session = ort.InferenceSession(
                str(self.weights_path), providers=self.providers
            )

    def restore(
        self,
        source_rgb: np.ndarray,
        *,
        base_4x: np.ndarray,
        scale: int,
        target_shape: tuple[int, int, int],
        case_id: str | None = None,
    ) -> tuple[np.ndarray, dict[str, Any]]:
        inp = (source_rgb.astype(np.float32) / 255.0).transpose(2, 0, 1)[None, ...]
        input_name = self._session.get_inputs()[0].name
        outputs = self._session.run(None, {input_name: inp})
        raw = np.asarray(outputs[0])
        if raw.ndim == 4 and raw.shape[0] == 1:
            raw = raw[0]
        if raw.ndim == 3 and raw.shape[0] == 3 and raw.shape[2] != 3:
            raw = raw.transpose(1, 2, 0)
        if raw.dtype != np.uint8:
            if not np.all(np.isfinite(raw)):
                raise ValueError("ONNX model output contains non-finite values (NaN or Inf)")
            raw = np.clip(np.rint(raw * 255.0), 0, 255).astype(np.uint8)
        out = _enforce_exact_shape(raw, target_shape, "onnxruntime_output")
        return out, {"weights_path": str(self.weights_path), "providers": self.providers}


def _resolve_torch_device(torch_mod: Any, device: str) -> str:
    if device != "auto":
        return device
    backends = getattr(torch_mod, "backends", None)
    mps = getattr(backends, "mps", None)
    if mps is not None and callable(getattr(mps, "is_available", None)) and mps.is_available():
        return "mps"
    cuda = getattr(torch_mod, "cuda", None)
    if cuda is not None and callable(getattr(cuda, "is_available", None)) and cuda.is_available():
        return "cuda"
    return "cpu"


class TorchSpandrelRestorationBackend:
    """PyTorch + Spandrel restoration backend with lazy imports, optional tiling, and SHA-256 provenance."""

    backend_name = "torch_spandrel"

    def __init__(
        self,
        weights_path: str | Path,
        *,
        model_id: str | None = None,
        device: str = "cpu",
        tile_core: int | None = None,
        tile_context: int = 32,
        model: Any = None,
    ) -> None:
        self.weights_path = Path(weights_path)
        if not self.weights_path.is_file():
            raise FileNotFoundError(f"PyTorch weights file not found: {self.weights_path}")
        if tile_core is not None and (isinstance(tile_core, bool) or not isinstance(tile_core, int) or tile_core <= 0):
            raise ValueError(f"tile_core must be a positive integer or None, got {tile_core!r}")
        if isinstance(tile_context, bool) or not isinstance(tile_context, int) or tile_context < 0:
            raise ValueError(f"tile_context must be a non-negative integer, got {tile_context!r}")
        self.model_id = model_id or self.weights_path.stem
        self.weights_sha256 = _sha256_file(self.weights_path)
        self.tile_core = tile_core
        self.tile_context = tile_context

        try:
            self._torch = importlib.import_module("torch")
            spandrel = importlib.import_module("spandrel")
        except ModuleNotFoundError as exc:
            raise BackendUnavailableError(
                "torch and spandrel are required for torch_spandrel backend"
            ) from exc

        self.device = _resolve_torch_device(self._torch, device)
        if model is not None:
            self._model = model
        else:
            descriptor = spandrel.ModelLoader().load_from_file(str(self.weights_path))
            self._model = descriptor.model.to(self.device).eval()

    def _infer_tile(self, tile_rgb: np.ndarray, *, scale: int) -> np.ndarray:
        torch = self._torch
        inp = (
            torch.from_numpy(tile_rgb.astype(np.float32) / 255.0)
            .permute(2, 0, 1)
            .unsqueeze(0)
            .to(self.device)
        )
        with torch.no_grad():
            pred = self._model(inp)
        arr = pred.squeeze(0).permute(1, 2, 0).detach().cpu().numpy()
        if arr.dtype != np.uint8:
            if not np.all(np.isfinite(arr)):
                raise ValueError("Torch/Spandrel model output contains non-finite values (NaN or Inf)")
            arr = np.clip(np.rint(arr * 255.0), 0, 255).astype(np.uint8)
        expected = (tile_rgb.shape[0] * scale, tile_rgb.shape[1] * scale, 3)
        return _enforce_exact_shape(arr, expected, "torch_spandrel_output")

    def _infer_tiled(
        self,
        source_rgb: np.ndarray,
        *,
        scale: int,
        target_shape: tuple[int, int, int],
    ) -> tuple[np.ndarray, int]:
        height, width = source_rgb.shape[:2]
        core = int(self.tile_core)
        context = self.tile_context
        out = np.zeros(target_shape, dtype=np.uint8)
        tiles = 0
        for y in range(0, height, core):
            for x in range(0, width, core):
                right = min(x + core, width)
                bottom = min(y + core, height)
                left_ctx = max(0, x - context)
                top_ctx = max(0, y - context)
                right_ctx = min(width, right + context)
                bottom_ctx = min(height, bottom + context)
                tile = np.ascontiguousarray(source_rgb[top_ctx:bottom_ctx, left_ctx:right_ctx])
                pred_tile = self._infer_tile(tile, scale=scale)
                px = (x - left_ctx) * scale
                py = (y - top_ctx) * scale
                out[y * scale : bottom * scale, x * scale : right * scale] = pred_tile[
                    py : py + (bottom - y) * scale,
                    px : px + (right - x) * scale,
                ]
                tiles += 1
        return out, tiles

    def restore(
        self,
        source_rgb: np.ndarray,
        *,
        base_4x: np.ndarray,
        scale: int,
        target_shape: tuple[int, int, int],
        case_id: str | None = None,
    ) -> tuple[np.ndarray, dict[str, Any]]:
        height, width = source_rgb.shape[:2]
        if self.tile_core is not None and max(height, width) > self.tile_core:
            out, tiles = self._infer_tiled(source_rgb, scale=scale, target_shape=target_shape)
        else:
            out = self._infer_tile(source_rgb, scale=scale)
            tiles = 1
        out = _enforce_exact_shape(out, target_shape, "torch_spandrel_output")
        return out, {
            "weights_path": str(self.weights_path),
            "device": self.device,
            "tile_core": self.tile_core,
            "tile_context": self.tile_context if tiles > 1 else 0,
            "tiles": tiles,
        }


_REALESR_OPTION_KEYS = frozenset(
    {
        "app_home",
        "engine_path",
        "model_dir",
        "model_id",
        "verify_hashes",
        "tile_threshold",
        "detail_blend_weight",
        "command_runner",
    }
)
_HYBRID_OPTION_KEYS = _REALESR_OPTION_KEYS | frozenset(
    {
        "comfy_backend",
        "bundle",
        "root",
        "address",
        "probe_timeout",
        "probe_fn",
    }
)


def _validate_option_keys(cls_name: str, options: Mapping[str, Any], allowed: frozenset[str]) -> None:
    unexpected = sorted(set(options) - allowed)
    if unexpected:
        raise TypeError(f"{cls_name}.__init__() got unexpected keyword argument(s): {', '.join(unexpected)}")


def _build_hybrid_backend(options: Mapping[str, Any]) -> Any:
    from fidelis.studio.hybrid_texture import HybridTextureBackend, RealESRGANNCNNBackend

    address = str(options.get("address", "http://127.0.0.1:8188"))
    comfy_backend = options.get("comfy_backend")
    if comfy_backend is None and options.get("bundle") is not None:
        comfy_backend = ComfyRestorationBackend(
            options["bundle"],
            root=options.get("root"),
            address=address,
        )
    realesr_kwargs = {
        key: options[key]
        for key in _REALESR_OPTION_KEYS
        if key in options
    }
    realesr_backend = RealESRGANNCNNBackend(**realesr_kwargs)
    return HybridTextureBackend(
        comfy_backend=comfy_backend,
        realesr_backend=realesr_backend,
        address=address,
        probe_timeout=float(options.get("probe_timeout", 1.5)),
        probe_fn=options.get("probe_fn"),
        model_id=options.get("model_id"),
    )


class RealESRGANRestorationBackend:
    """Zero-cost local NCNN-Vulkan RealeSR-general-v3 restoration backend."""

    backend_name = "realesrgan_ncnn_vulkan"

    def __init__(self, backend: Any | None = None, **options: Any) -> None:
        _validate_option_keys(type(self).__name__, options, _REALESR_OPTION_KEYS)
        try:
            from fidelis.studio.comfy import BackendUnavailable
            from fidelis.studio.hybrid_texture import MODEL_NAME, RealESRGANNCNNBackend
        except ModuleNotFoundError as exc:
            raise BackendUnavailableError(
                f"Local NCNN restoration dependencies unavailable: {exc}"
            ) from exc

        self._unavailable_exc = BackendUnavailable
        if backend is not None:
            self._backend = backend
        else:
            kwargs = dict(options)
            if kwargs.get("model_id") is None:
                kwargs["model_id"] = MODEL_NAME
            self._backend = RealESRGANNCNNBackend(**kwargs)
        self.model_id = str(getattr(self._backend, "model_id", options.get("model_id") or MODEL_NAME))

    @property
    def weights_sha256(self) -> str:
        return str(getattr(self._backend, "weights_sha256", "unverified_until_run"))

    def restore(
        self,
        source_rgb: np.ndarray,
        *,
        base_4x: np.ndarray,
        scale: int,
        target_shape: tuple[int, int, int],
        case_id: str | None = None,
    ) -> tuple[np.ndarray, dict[str, Any]]:
        try:
            raw_out, meta = self._backend.restore(
                source_rgb,
                base_4x=base_4x,
                scale=scale,
                target_shape=target_shape,
                case_id=case_id,
            )
        except self._unavailable_exc as exc:
            raise BackendUnavailableError(str(exc)) from exc
        out = _enforce_exact_shape(raw_out, target_shape, "realesrgan_ncnn_output")
        return out, dict(meta)


class HybridRestorationBackend:
    """Zero-cost ComfyUI -> M1 RealeSR-general-v3 -> CPU Lanczos-3 hybrid backend."""

    backend_name = "hybrid_zero_cost_texture"

    def __init__(self, backend: Any | None = None, **options: Any) -> None:
        _validate_option_keys(type(self).__name__, options, _HYBRID_OPTION_KEYS)
        try:
            from fidelis.studio.comfy import BackendUnavailable
        except ModuleNotFoundError as exc:
            raise BackendUnavailableError(
                f"Hybrid texture restoration dependencies unavailable: {exc}"
            ) from exc

        self._unavailable_exc = BackendUnavailable
        self._backend = backend if backend is not None else _build_hybrid_backend(options)

    @property
    def model_id(self) -> str:
        return str(getattr(self._backend, "model_id", "hybrid_zero_cost_texture"))

    @property
    def weights_sha256(self) -> str:
        return str(getattr(self._backend, "weights_sha256", "unresolved_until_run"))

    def restore(
        self,
        source_rgb: np.ndarray,
        *,
        base_4x: np.ndarray,
        scale: int,
        target_shape: tuple[int, int, int],
        case_id: str | None = None,
    ) -> tuple[np.ndarray, dict[str, Any]]:
        try:
            raw_out, meta = self._backend.restore(
                source_rgb,
                base_4x=base_4x,
                scale=scale,
                target_shape=target_shape,
                case_id=case_id,
            )
        except self._unavailable_exc as exc:
            raise BackendUnavailableError(str(exc)) from exc
        out = _enforce_exact_shape(raw_out, target_shape, "hybrid_texture_output")
        return out, dict(meta)


def _backend_runtime_and_options(
    backend: RestorationBackend, extra: Mapping[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    runtime: dict[str, Any] = {
        "python": platform.python_version(),
        "numpy": np.__version__,
    }
    options: dict[str, Any] = {}
    for attr in ("device", "tile_core", "tile_context", "providers", "workflow_sha256", "deadline_seconds"):
        if hasattr(backend, attr):
            val = getattr(backend, attr)
            if val is not None:
                options[attr] = val
    inner = getattr(backend, "_backend", None)
    if inner is not None:
        for attr in ("detail_blend_weight", "tile_threshold"):
            if hasattr(inner, attr):
                val = getattr(inner, attr)
                if val is not None:
                    options[attr] = val
    for key in ("device", "tile_core", "tile_context", "tiles", "providers", "workflow_sha256", "family"):
        if key in extra and extra[key] is not None:
            options.setdefault(key, extra[key])
    if "device" in options:
        runtime["device"] = options["device"]
    return runtime, options


class RestorationRunner:
    """Unified restoration runner with exact-grid enforcement and M2 texture guard."""

    def __init__(self, backend: RestorationBackend) -> None:
        self.backend = backend

    def run(
        self,
        source_rgb: np.ndarray,
        *,
        scale: int = 4,
        target_size: tuple[int, int] | None = None,
        rois: Sequence[Mapping[str, Any]] = (),
        roi_space: str = "target",
        apply_texture_guard: bool = True,
        blend: RegionBlend | None = None,
        use_sobel_heuristic: bool = True,
        case_id: str | None = None,
        raw_checkpoint_callback: Callable[[Mapping[str, Any]], None] | None = None,
    ) -> RestorationResult:
        src = _validate_rgb_uint8(source_rgb, "source_rgb")
        if scale < 1:
            raise ValueError(f"scale must be >= 1, got {scale}")

        sh, sw, _ = src.shape
        if target_size is not None:
            tw, th = int(target_size[0]), int(target_size[1])
            if tw < 1 or th < 1:
                raise DimensionMismatchError(f"Invalid target_size {target_size}")
        else:
            tw, th = sw * scale, sh * scale
        target_shape = (th, tw, 3)

        target_rois = _normalize_rois_for_guard(
            rois, source_shape=(sh, sw), target_shape=(th, tw), roi_space=roi_space
        )
        validate_rois_fn = getattr(self.backend, "validate_normalized_rois", None)
        if callable(validate_rois_fn):
            validate_rois_fn(target_rois)

        base_4x = _bicubic_upscale(src, tw, th)
        raw_candidate, extra = self.backend.restore(
            src,
            base_4x=base_4x,
            scale=scale,
            target_shape=target_shape,
            case_id=case_id,
        )
        raw_candidate = _enforce_exact_shape(raw_candidate, target_shape, "raw_candidate")

        if raw_checkpoint_callback is not None:
            model_runtime, model_options = _backend_runtime_and_options(self.backend, extra)
            raw_checkpoint_callback(
                {
                    "source_rgb": src,
                    "base_4x": base_4x,
                    "raw_candidate": raw_candidate,
                    "scale": int(scale),
                    "target_shape": target_shape,
                    "model_id": self.backend.model_id,
                    "backend": self.backend.backend_name,
                    "weights_sha256": self.backend.weights_sha256,
                    "normalized_rois": target_rois,
                    "case_id": case_id,
                    "extra": dict(extra),
                    "model_runtime": model_runtime,
                    "model_options": model_options,
                }
            )

        guard_receipt: dict[str, Any] | None = None
        drift_report: dict[str, Any] | None = None

        if apply_texture_guard:
            masks, guard_receipt = build_roi_protection_masks(
                base_4x,
                target_rois,
                use_sobel_heuristic=use_sobel_heuristic,
            )
            # An absent texture ROI is not permission to replace the image.
            # Only explicitly texture-allowed or unlocked regions can receive
            # synthetic detail. The remainder stays on the precision base.
            semantic_masks: dict[str, np.ndarray | None] = {
                "skin": None,
                "hair": None,
                "fabric": None,
            }
            unlocked_mask: np.ndarray | None = None
            for r in target_rois:
                if r.get("policy") != "texture_allowed" and r.get("override") != "unlock":
                    continue
                # Preserve semantic ROI channels so a caller's RegionBlend
                # controls skin, hair and fabric independently.  A deliberate
                # unlock for a structural ROI remains explicit permission, but
                # has no semantic texture class and therefore uses fabric.
                channel = r["kind"] if r["kind"] in semantic_masks else "fabric"
                if semantic_masks[channel] is None:
                    semantic_masks[channel] = np.zeros((th, tw), dtype=np.float32)
                rx, ry, rw, rh = r["rect"]
                semantic_masks[channel][ry : ry + rh, rx : rx + rw] = 1.0
                if r.get("override") == "unlock":
                    if unlocked_mask is None:
                        unlocked_mask = np.zeros((th, tw), dtype=np.float32)
                    unlocked_mask[ry : ry + rh, rx : rx + rw] = 1.0
            permitted = np.array(masks["interior_texture"], dtype=np.float32, copy=True)
            active_sum: np.ndarray | None = None
            for channel_mask in semantic_masks.values():
                if channel_mask is not None:
                    active_sum = channel_mask.copy() if active_sum is None else active_sum + channel_mask
            if active_sum is not None:
                np.clip(active_sum, 0.0, 1.0, out=active_sum)
                np.maximum(permitted, active_sum, out=permitted)
            # An explicit unlock is a deliberate texture authorization even
            # when its original policy was preserve, so it cannot depend on
            # the texture-allowed interior mask. Explicit locks still win at
            # the final protection boundary below.
            if unlocked_mask is not None:
                np.maximum(permitted, unlocked_mask, out=permitted)
            permitted *= 1.0 - masks["protected"]
            for channel, channel_mask in semantic_masks.items():
                if channel_mask is not None:
                    channel_mask *= permitted
            confidence_mask = permitted
            active_blend = (
                blend
                if blend is not None
                else RegionBlend(fabric=1.0, edge_protection=0.5)
            )
            guarded, _alpha = compose_regions(
                base_4x,
                raw_candidate,
                skin=semantic_masks["skin"],
                hair=semantic_masks["hair"],
                fabric=semantic_masks["fabric"],
                protected=masks["protected"],
                confidence=confidence_mask,
                edge_guard=masks["edge_guard"],
                interior_texture=permitted,
                blend=active_blend,
            )
            drift_report = screen_internal_drift(
                base_4x,
                guarded,
                rois=target_rois,
                protected=masks["protected"],
            )
            final_image = _enforce_exact_shape(guarded, target_shape, "guarded_output")
        else:
            final_image = raw_candidate.copy()

        provenance = RestorationProvenance(
            model_id=self.backend.model_id,
            backend=self.backend.backend_name,
            weights_sha256=self.backend.weights_sha256,
            scale=scale,
            source_shape=(int(sh), int(sw), 3),
            target_shape=target_shape,
            texture_guard_applied=bool(apply_texture_guard),
            extra=dict(extra),
        )
        return RestorationResult(
            image=final_image,
            raw_candidate=raw_candidate,
            provenance=provenance,
            guard_receipt=guard_receipt,
            drift_report=drift_report,
        )

    def to_comparator_runner(
        self,
        *,
        apply_texture_guard: bool = True,
        scale: int = 4,
    ) -> Callable[[dict[str, Any], Path, Path], ComparatorOutput]:
        """Adapt this runner for fidelis.eval.comparators.run_comparators()."""

        def _runner(
            case: dict[str, Any], source_path: Path, dest_path: Path
        ) -> ComparatorOutput:
            if case.get("expected_behavior") == "reject_unsupported_input":
                return ComparatorOutput(
                    output_path=None,
                    status="rejected_unsupported",
                    settings={"model_id": self.backend.model_id, "backend": self.backend.backend_name},
                    cost_usd=0.0,
                    is_imported=(self.backend.backend_name == "imported"),
                )
            t0 = time.perf_counter()
            try:
                with Image.open(source_path) as img:
                    src = np.asarray(img.convert("RGB"), dtype=np.uint8)
                td = case.get("target_dimensions")
                target_size = (int(td[0]), int(td[1])) if td else None
                res = self.run(
                    src,
                    scale=scale,
                    target_size=target_size,
                    rois=case.get("rois") or (),
                    roi_space=str(case.get("roi_space", "auto")),
                    apply_texture_guard=apply_texture_guard,
                    case_id=case.get("id"),
                )
                dest_path.parent.mkdir(parents=True, exist_ok=True)
                tmp = dest_path.with_suffix(".tmp.png")
                Image.fromarray(res.image).save(tmp, format="PNG")
                tmp.replace(dest_path)
                elapsed = round(time.perf_counter() - t0, 4)
                return ComparatorOutput(
                    output_path=dest_path,
                    status="completed",
                    settings=res.provenance.to_dict(),
                    elapsed_seconds=elapsed,
                    cost_usd=0.0,
                    is_imported=(self.backend.backend_name == "imported"),
                )
            except BackendUnavailableError as exc:
                return ComparatorOutput(
                    output_path=None,
                    status="unavailable",
                    settings={"model_id": self.backend.model_id, "backend": self.backend.backend_name},
                    error=str(exc),
                    is_imported=(self.backend.backend_name == "imported"),
                )
            except (DimensionMismatchError, FileNotFoundError, ValueError, OSError) as exc:
                return ComparatorOutput(
                    output_path=None,
                    status="failed",
                    settings={"model_id": self.backend.model_id, "backend": self.backend.backend_name},
                    error=str(exc),
                    is_imported=(self.backend.backend_name == "imported"),
                )

        return _runner


def create_restoration_runner(backend: str, **kwargs: Any) -> RestorationRunner:
    """Factory creating a RestorationRunner for the requested backend."""
    name = backend.strip().lower()
    if name == "bicubic":
        return RestorationRunner(BicubicBaselineBackend(**kwargs))
    if name == "imported":
        return RestorationRunner(ImportedRestorationBackend(**kwargs))
    if name == "comfyui":
        return RestorationRunner(ComfyRestorationBackend(**kwargs))
    if name == "onnxruntime":
        return RestorationRunner(OnnxRestorationBackend(**kwargs))
    if name == "torch_spandrel":
        return RestorationRunner(TorchSpandrelRestorationBackend(**kwargs))
    if name in ("realesrgan_ncnn", "realesrgan_ncnn_vulkan", "realesr"):
        return RestorationRunner(RealESRGANRestorationBackend(**kwargs))
    if name in ("hybrid", "hybrid_zero_cost_texture"):
        return RestorationRunner(HybridRestorationBackend(**kwargs))
    if name in ("checkpoint", "checkpoint_replay"):
        return RestorationRunner(CheckpointRestorationBackend(**kwargs))
    raise ValueError(f"Unknown restoration backend: {backend!r}")
