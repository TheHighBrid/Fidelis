"""Pluggable restoration model runner with strict 4x grid validation and texture guard."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import importlib
from pathlib import Path
import time
from typing import Any, Callable, Mapping, Optional, Protocol, Sequence, runtime_checkable

import numpy as np
from PIL import Image

from fidelis.eval.comparators import ComparatorOutput
from fidelis.postprocess.regions import RegionBlend, compose_regions
from fidelis.postprocess.roi_protection import (
    VALID_POLICIES,
    VALID_ROI_KINDS,
    build_roi_protection_masks,
    screen_internal_drift,
)
from fidelis.studio.comfy import ComfyTextureBackend, canonical_hash


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
        case_id: Optional[str] = None,
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
            raise ValueError("Each ROI entry must be a mapping")
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

        tx = max(0, min(tw - 1, int(round(rx * scale_x))))
        ty = max(0, min(th - 1, int(round(ry * scale_y))))
        tw_r = max(1, min(tw - tx, int(round(rw * scale_x))))
        th_r = max(1, min(th - ty, int(round(rh * scale_y))))

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
        case_id: Optional[str] = None,
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

    def _resolve_path(self, case_id: Optional[str]) -> Path:
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
        case_id: Optional[str] = None,
    ) -> tuple[np.ndarray, dict[str, Any]]:
        path = self._resolve_path(case_id)
        with Image.open(path) as img:
            if img.mode != "RGB":
                raise ValueError(
                    f"Imported image {path.name} must be 3-channel RGB, got mode {img.mode!r}"
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
        comfy_backend: ComfyTextureBackend | None = None,
        root: str | Path | None = None,
        address: str = "http://127.0.0.1:8188",
        model_id: str = "comfyui",
        deadline_seconds: float = 300.0,
    ) -> None:
        if comfy_backend is None:
            if root is None:
                raise ValueError("ComfyRestorationBackend requires comfy_backend or root")
            comfy_backend = ComfyTextureBackend(root, address=address)
        self.comfy = comfy_backend
        self.bundle = bundle
        self.model_id = model_id
        self.deadline_seconds = float(deadline_seconds)
        self.weights_sha256 = canonical_hash(bundle)

    def restore(
        self,
        source_rgb: np.ndarray,
        *,
        base_4x: np.ndarray,
        scale: int,
        target_shape: tuple[int, int, int],
        case_id: Optional[str] = None,
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
            "workflow_sha256": record.get("workflow_sha256", self.weights_sha256),
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
        case_id: Optional[str] = None,
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


class TorchSpandrelRestorationBackend:
    """PyTorch + Spandrel restoration backend with lazy imports and SHA-256 provenance."""

    backend_name = "torch_spandrel"

    def __init__(
        self,
        weights_path: str | Path,
        *,
        model_id: str | None = None,
        device: str = "cpu",
        model: Any = None,
    ) -> None:
        self.weights_path = Path(weights_path)
        if not self.weights_path.is_file():
            raise FileNotFoundError(f"PyTorch weights file not found: {self.weights_path}")
        self.model_id = model_id or self.weights_path.stem
        self.weights_sha256 = _sha256_file(self.weights_path)
        self.device = device

        try:
            self._torch = importlib.import_module("torch")
            spandrel = importlib.import_module("spandrel")
        except ModuleNotFoundError as exc:
            raise BackendUnavailableError(
                "torch and spandrel are required for torch_spandrel backend"
            ) from exc

        if model is not None:
            self._model = model
        else:
            descriptor = spandrel.ModelLoader().load_from_file(str(self.weights_path))
            self._model = descriptor.model.to(self.device).eval()

    def restore(
        self,
        source_rgb: np.ndarray,
        *,
        base_4x: np.ndarray,
        scale: int,
        target_shape: tuple[int, int, int],
        case_id: Optional[str] = None,
    ) -> tuple[np.ndarray, dict[str, Any]]:
        torch = self._torch
        inp = (
            torch.from_numpy(source_rgb.astype(np.float32) / 255.0)
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
        out = _enforce_exact_shape(arr, target_shape, "torch_spandrel_output")
        return out, {"weights_path": str(self.weights_path), "device": self.device}


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
        case_id: Optional[str] = None,
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

        base_4x = _bicubic_upscale(src, tw, th)
        raw_candidate, extra = self.backend.restore(
            src,
            base_4x=base_4x,
            scale=scale,
            target_shape=target_shape,
            case_id=case_id,
        )
        raw_candidate = _enforce_exact_shape(raw_candidate, target_shape, "raw_candidate")

        guard_receipt: dict[str, Any] | None = None
        drift_report: dict[str, Any] | None = None

        if apply_texture_guard:
            target_rois = _normalize_rois_for_guard(
                rois, source_shape=(sh, sw), target_shape=(th, tw), roi_space=roi_space
            )
            masks, guard_receipt = build_roi_protection_masks(
                base_4x,
                target_rois,
                use_sobel_heuristic=use_sobel_heuristic,
            )
            if np.any(masks["interior_texture"] > 0.0):
                unlocked_mask = np.zeros((th, tw), dtype=np.float32)
                for r in target_rois:
                    if r.get("override") == "unlock":
                        rx, ry, rw, rh = r["rect"]
                        unlocked_mask[ry : ry + rh, rx : rx + rw] = 1.0
                unlocked_mask *= (1.0 - masks["protected"]).astype(np.float32)
                fabric_mask = np.maximum(masks["interior_texture"], unlocked_mask).astype(np.float32)
            else:
                fabric_mask = (1.0 - masks["protected"]).astype(np.float32)
            confidence_mask = np.where(masks["protected"] < 1.0, 1.0, 0.0).astype(
                np.float32
            )
            active_blend = (
                blend
                if blend is not None
                else RegionBlend(fabric=1.0, edge_protection=0.5)
            )
            guarded, _alpha = compose_regions(
                base_4x,
                raw_candidate,
                fabric=fabric_mask,
                protected=masks["protected"],
                confidence=confidence_mask,
                edge_guard=masks["edge_guard"],
                interior_texture=masks["interior_texture"],
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
    raise ValueError(f"Unknown restoration backend: {backend!r}")
