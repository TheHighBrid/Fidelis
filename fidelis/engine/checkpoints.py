"""Resumable raw inference checkpoints and fail-closed replay backend (F13 / #135).

Persists unguarded raw model output (`raw_candidate.npy`) and the exact
paired 4x bicubic reference (`bicubic_base.npy`) immediately after inference
and exact-shape validation, before texture guard composition, drift screening,
or evaluation.  The receipt (`checkpoint_receipt.json`) is atomically published
last so partial writes never pass verification.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import uuid
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

SCHEMA_VERSION = "fidelis.raw_checkpoint.v1"
RAW_CHECKPOINT_RECEIPT_FILENAME = "checkpoint_receipt.json"
RAW_CANDIDATE_FILENAME = "raw_candidate.npy"
BICUBIC_BASE_FILENAME = "bicubic_base.npy"

_CORE_ENGINE_FILES: tuple[str, ...] = (
    "fidelis/engine/restoration_runner.py",
    "fidelis/engine/checkpoints.py",
    "fidelis/studio/audition.py",
    "fidelis/postprocess/regions.py",
    "fidelis/postprocess/roi_protection.py",
)


class CheckpointError(ValueError):
    """Raised when a raw generation checkpoint is missing, partial, tampered, or mismatched."""


def canonical_json_sha256(value: Any) -> str:
    """Return a deterministic SHA-256 hex digest of a JSON-serializable structure."""
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def sha256_file(path: Path) -> str:
    """Stream-hash file contents without loading large arrays into RAM."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def compute_rgb_pixel_sha256(arr: np.ndarray) -> str:
    """Compute a bounded-memory SHA-256 over an HxWx3 uint8 RGB array's shape and pixels."""
    if not isinstance(arr, np.ndarray) or arr.ndim != 3 or arr.shape[2] != 3 or arr.dtype != np.uint8:
        raise CheckpointError(
            f"Expected HxWx3 uint8 array for pixel digest, got shape={getattr(arr, 'shape', None)}, "
            f"dtype={getattr(arr, 'dtype', None)}"
        )
    h, w, _ = arr.shape
    if h < 1 or w < 1:
        raise CheckpointError(f"Array dimensions must be non-empty, got {arr.shape}")
    digest = hashlib.sha256(f"{h}x{w}:uint8:RGB:".encode("ascii"))
    strip_rows = 64
    for y0 in range(0, h, strip_rows):
        strip = np.ascontiguousarray(arr[y0 : min(h, y0 + strip_rows)], dtype=np.uint8)
        digest.update(strip.tobytes())
    return digest.hexdigest()


def capture_code_identity(extra_paths: Sequence[str | Path] = ()) -> dict[str, Any]:
    """Record current repository commit, dirty flag, and core file SHA-256 digests."""
    repo_root = Path(__file__).resolve().parents[2]
    code_commit: str | None = None
    working_tree_dirty: bool | None = None
    try:
        code_commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.strip()
        working_tree_dirty = bool(
            subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=repo_root,
                check=True,
                capture_output=True,
                text=True,
                timeout=5,
            ).stdout.strip()
        )
    except (OSError, subprocess.SubprocessError):
        pass

    file_hashes: dict[str, str] = {}
    for rel in _CORE_ENGINE_FILES:
        candidate = repo_root / rel
        if candidate.is_file():
            file_hashes[rel] = sha256_file(candidate)
    for item in extra_paths:
        p = Path(item)
        if p.is_file():
            try:
                key = str(p.resolve().relative_to(repo_root.resolve()))
            except ValueError:
                key = p.name
            file_hashes[key] = sha256_file(p)

    return {
        "code_commit": code_commit,
        "working_tree_dirty": working_tree_dirty,
        "file_hashes": file_hashes,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }


def _resolve_safe_artifact_path(
    checkpoint_dir: Path,
    rel_path: Any,
    *,
    expected_role: str,
) -> Path:
    if not isinstance(rel_path, str) or not rel_path.strip():
        raise CheckpointError(f"Checkpoint artifact {expected_role!r} missing path")
    rel = Path(rel_path)
    if rel.is_absolute() or ".." in rel.parts:
        raise CheckpointError(f"Checkpoint artifact path escapes directory: {rel_path!r}")
    if rel.suffix.lower() == ".png" or rel.name == "candidate_4x.png":
        raise CheckpointError(
            f"Guarded/PNG output {rel_path!r} must never be used as raw checkpoint artifact {expected_role!r}"
        )
    if rel.suffix.lower() != ".npy":
        raise CheckpointError(f"Checkpoint artifact {expected_role!r} must be .npy, got {rel_path!r}")

    root_resolved = checkpoint_dir.resolve()
    candidate = root_resolved / rel
    if not candidate.parent.resolve().is_relative_to(root_resolved):
        raise CheckpointError(f"Checkpoint artifact directory escapes root: {rel_path!r}")
    if candidate.is_symlink() or (candidate.exists() and not candidate.resolve().is_relative_to(root_resolved)):
        raise CheckpointError(f"Checkpoint artifact symlink escapes root: {rel_path!r}")
    if not candidate.is_file():
        raise CheckpointError(f"Checkpoint artifact missing for {expected_role!r}: {candidate}")
    return candidate


def _write_npy_atomic(path: Path, array: np.ndarray) -> dict[str, Any]:
    if not isinstance(array, np.ndarray) or array.ndim != 3 or array.shape[2] != 3 or array.dtype != np.uint8:
        raise CheckpointError("Checkpoint array must be HxWx3 uint8")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    arr = np.ascontiguousarray(array, dtype=np.uint8)
    try:
        with tmp.open("wb") as handle:
            np.save(handle, arr, allow_pickle=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise

    return {
        "path": path.name,
        "sha256": sha256_file(path),
        "pixel_sha256": compute_rgb_pixel_sha256(arr),
        "shape": [int(v) for v in arr.shape],
        "dtype": "uint8",
        "file_bytes": int(path.stat().st_size),
    }


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    text = json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n"
    try:
        with tmp.open("w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    return sha256_file(path)


def _read_npy_header(handle: Any) -> tuple[tuple[int, ...], bool, np.dtype[Any], int]:
    version = np.lib.format.read_magic(handle)
    if version == (1, 0):
        shape, fortran_order, dtype = np.lib.format.read_array_header_1_0(handle)
    elif version == (2, 0):
        shape, fortran_order, dtype = np.lib.format.read_array_header_2_0(handle)
    else:
        shape, fortran_order, dtype = np.lib.format._read_array_header(handle, version)
    data_offset = int(handle.tell())
    return tuple(int(v) for v in shape), bool(fortran_order), np.dtype(dtype), data_offset


def load_validated_npy_mmap(
    path: Path,
    *,
    expected_shape: tuple[int, int, int],
    expected_file_sha256: str,
    expected_pixel_sha256: str,
    expected_role: str,
) -> np.ndarray:
    """Validate .npy header, exact file extent, and digests before mmap reading."""
    try:
        with path.open("rb") as handle:
            shape, fortran_order, dtype, data_offset = _read_npy_header(handle)
    except Exception as exc:  # noqa: BLE001
        raise CheckpointError(f"Invalid .npy header for {expected_role!r} ({path.name}): {exc}") from exc

    if dtype.hasobject or dtype != np.dtype(np.uint8):
        raise CheckpointError(f"Checkpoint {expected_role!r} must have uint8 dtype, got {dtype!r}")
    if fortran_order:
        raise CheckpointError(f"Checkpoint {expected_role!r} must be C-contiguous, got Fortran order")
    if shape != tuple(expected_shape):
        raise CheckpointError(
            f"Checkpoint {expected_role!r} shape {shape} does not match expected {tuple(expected_shape)}"
        )

    expected_payload_bytes = int(np.prod(expected_shape, dtype=np.int64))
    expected_file_bytes = data_offset + expected_payload_bytes
    actual_file_bytes = int(path.stat().st_size)
    if actual_file_bytes != expected_file_bytes:
        raise CheckpointError(
            f"Checkpoint {expected_role!r} file size {actual_file_bytes} != expected {expected_file_bytes}"
        )

    actual_file_sha = sha256_file(path)
    if actual_file_sha != expected_file_sha256:
        raise CheckpointError(
            f"Checkpoint {expected_role!r} file SHA-256 mismatch ({actual_file_sha} != {expected_file_sha256})"
        )

    arr = np.load(path, mmap_mode="r", allow_pickle=False)
    if arr.shape != tuple(expected_shape) or arr.dtype != np.uint8:
        raise CheckpointError(f"Loaded mmap array mismatch for {expected_role!r}")

    actual_pixel_sha = compute_rgb_pixel_sha256(arr)
    if actual_pixel_sha != expected_pixel_sha256:
        raise CheckpointError(
            f"Checkpoint {expected_role!r} pixel SHA-256 mismatch ({actual_pixel_sha} != {expected_pixel_sha256})"
        )
    return arr


def save_raw_checkpoint(
    checkpoint_dir: str | Path,
    *,
    source_rgb: np.ndarray,
    base_4x: np.ndarray,
    raw_candidate: np.ndarray,
    scale: int,
    target_shape: tuple[int, int, int],
    model_id: str,
    backend: str,
    weights_sha256: str,
    normalized_rois: Sequence[Mapping[str, Any]] = (),
    case_id: str | None = None,
    source_file_sha256: str | None = None,
    source_path: str | Path | None = None,
    model_runtime: Mapping[str, Any] | None = None,
    model_options: Mapping[str, Any] | None = None,
    protocol_sha256: str | None = None,
    config_sha256: str | None = None,
    extra_provenance: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist raw_candidate.npy and bicubic_base.npy, then atomically publish the receipt last."""
    dest_dir = Path(checkpoint_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)

    if tuple(raw_candidate.shape) != tuple(target_shape):
        raise CheckpointError(
            f"raw_candidate shape {raw_candidate.shape} does not match target_shape {target_shape}"
        )
    if tuple(base_4x.shape) != tuple(target_shape):
        raise CheckpointError(
            f"base_4x shape {base_4x.shape} does not match target_shape {target_shape}"
        )

    resolved_source_file_sha = source_file_sha256
    if resolved_source_file_sha is None and source_path is not None:
        sp = Path(source_path)
        if not sp.is_file():
            raise CheckpointError(f"Source file missing when saving checkpoint: {sp}")
        resolved_source_file_sha = sha256_file(sp)

    norm_rois_list = [dict(r) for r in normalized_rois]
    runtime_dict = dict(model_runtime or {})
    options_dict = dict(model_options or {})

    raw_meta = _write_npy_atomic(dest_dir / RAW_CANDIDATE_FILENAME, raw_candidate)
    raw_meta["role"] = "raw_candidate"
    bic_meta = _write_npy_atomic(dest_dir / BICUBIC_BASE_FILENAME, base_4x)
    bic_meta["role"] = "bicubic_base"

    receipt: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "case_id": case_id,
        "source": {
            "source_file_sha256": resolved_source_file_sha,
            "source_pixel_sha256": compute_rgb_pixel_sha256(source_rgb),
            "source_shape": [int(v) for v in source_rgb.shape],
        },
        "target": {
            "scale": int(scale),
            "target_shape": [int(v) for v in target_shape],
        },
        "model": {
            "model_id": str(model_id),
            "backend": str(backend),
            "weights_sha256": str(weights_sha256),
            "runtime": runtime_dict,
            "runtime_sha256": canonical_json_sha256(runtime_dict),
            "options": options_dict,
            "options_sha256": canonical_json_sha256(options_dict),
            "extra_provenance": dict(extra_provenance or {}),
        },
        "rois": {
            "roi_space": "target",
            "normalized_rois": norm_rois_list,
            "normalized_rois_sha256": canonical_json_sha256(norm_rois_list),
        },
        "protocol": {
            "protocol_sha256": protocol_sha256,
            "config_sha256": config_sha256,
        },
        "generation_identity": capture_code_identity(),
        "artifacts": {
            "raw_candidate": raw_meta,
            "bicubic_base": bic_meta,
        },
    }

    receipt_path = dest_dir / RAW_CHECKPOINT_RECEIPT_FILENAME
    receipt_sha = _write_json_atomic(receipt_path, receipt)
    return {
        "checkpoint_dir": str(dest_dir),
        "receipt_path": str(receipt_path),
        "receipt_sha256": receipt_sha,
        "receipt": receipt,
    }


def make_raw_checkpoint_callback(
    checkpoint_dir: str | Path,
    *,
    source_file_sha256: str | None = None,
    source_path: str | Path | None = None,
    model_runtime: Mapping[str, Any] | None = None,
    model_options: Mapping[str, Any] | None = None,
    protocol_sha256: str | None = None,
    config_sha256: str | None = None,
    out_record: dict[str, Any] | None = None,
):
    """Build a RestorationRunner raw-checkpoint callback bound to the generation context."""

    def _callback(payload: Mapping[str, Any]) -> None:
        saved = save_raw_checkpoint(
            checkpoint_dir,
            source_rgb=payload["source_rgb"],
            base_4x=payload["base_4x"],
            raw_candidate=payload["raw_candidate"],
            scale=int(payload["scale"]),
            target_shape=tuple(payload["target_shape"]),
            model_id=str(payload["model_id"]),
            backend=str(payload["backend"]),
            weights_sha256=str(payload["weights_sha256"]),
            normalized_rois=payload.get("normalized_rois") or (),
            case_id=payload.get("case_id"),
            source_file_sha256=source_file_sha256,
            source_path=source_path,
            model_runtime=model_runtime,
            model_options=model_options,
            protocol_sha256=protocol_sha256,
            config_sha256=config_sha256,
            extra_provenance=payload.get("extra") or {},
        )
        if out_record is not None:
            out_record.clear()
            out_record.update(saved)

    return _callback


def _validate_artifact_entry(
    checkpoint_dir: Path,
    artifacts: Mapping[str, Any],
    *,
    key: str,
    expected_role: str,
    expected_shape: tuple[int, int, int],
) -> tuple[Path, Mapping[str, Any]]:
    entry = artifacts.get(key)
    if not isinstance(entry, Mapping):
        raise CheckpointError(f"Checkpoint missing artifact metadata for {key!r}")
    if entry.get("role") != expected_role:
        raise CheckpointError(
            f"Checkpoint artifact {key!r} has invalid role {entry.get('role')!r}; "
            f"expected {expected_role!r} (guarded final output cannot stand in for raw)"
        )
    if entry.get("dtype") != "uint8":
        raise CheckpointError(f"Checkpoint artifact {key!r} must be uint8, got {entry.get('dtype')!r}")
    if entry.get("shape") != list(expected_shape):
        raise CheckpointError(
            f"Checkpoint artifact {key!r} shape {entry.get('shape')} != expected {list(expected_shape)}"
        )
    resolved = _resolve_safe_artifact_path(checkpoint_dir, entry.get("path"), expected_role=expected_role)
    file_sha = entry.get("sha256")
    pixel_sha = entry.get("pixel_sha256")
    if not isinstance(file_sha, str) or len(file_sha) != 64:
        raise CheckpointError(f"Checkpoint artifact {key!r} missing valid sha256")
    if not isinstance(pixel_sha, str) or len(pixel_sha) != 64:
        raise CheckpointError(f"Checkpoint artifact {key!r} missing valid pixel_sha256")
    if entry.get("file_bytes") != int(resolved.stat().st_size):
        raise CheckpointError(
            f"Checkpoint artifact {key!r} file_bytes mismatch: "
            f"{resolved.stat().st_size} != {entry.get('file_bytes')}"
        )
    return resolved, entry


class CheckpointRestorationBackend:
    """Explicit replay backend loading verified raw checkpoints without executing inference."""

    backend_name = "checkpoint_replay"

    def __init__(
        self,
        checkpoint_dir: str | Path,
        *,
        expected_case_id: str | None = None,
        expected_source_file_sha256: str | None = None,
        require_source_file_sha256: bool = False,
        expected_scale: int | None = None,
        expected_target_shape: tuple[int, int, int] | None = None,
        expected_model_id: str | None = None,
        expected_backend: str | None = None,
        expected_weights_sha256: str | None = None,
        expected_runtime: Mapping[str, Any] | None = None,
        expected_options: Mapping[str, Any] | None = None,
        expected_normalized_rois: Sequence[Mapping[str, Any]] | None = None,
        expected_protocol_sha256: str | None = None,
        expected_config_sha256: str | None = None,
        evaluation_context: Mapping[str, Any] | None = None,
    ) -> None:
        self.checkpoint_dir = Path(checkpoint_dir)
        self.receipt_path = self.checkpoint_dir / RAW_CHECKPOINT_RECEIPT_FILENAME
        if not self.receipt_path.is_file():
            raise CheckpointError(
                f"Incomplete or missing raw checkpoint: {self.receipt_path} does not exist"
            )
        try:
            receipt = json.loads(self.receipt_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CheckpointError(f"Malformed checkpoint receipt {self.receipt_path}: {exc}") from exc

        if not isinstance(receipt, Mapping) or receipt.get("schema_version") != SCHEMA_VERSION:
            raise CheckpointError(
                f"Unsupported or invalid checkpoint receipt schema in {self.receipt_path}"
            )

        self.receipt = copy.deepcopy(dict(receipt))
        self.receipt_sha256 = sha256_file(self.receipt_path)
        self._expected_normalized_rois = (
            [dict(r) for r in expected_normalized_rois]
            if expected_normalized_rois is not None
            else None
        )
        self._evaluation_context = dict(evaluation_context or {})

        self._validate_receipt_structure(
            expected_case_id=expected_case_id,
            expected_source_file_sha256=expected_source_file_sha256,
            require_source_file_sha256=require_source_file_sha256,
            expected_scale=expected_scale,
            expected_target_shape=expected_target_shape,
            expected_model_id=expected_model_id,
            expected_backend=expected_backend,
            expected_weights_sha256=expected_weights_sha256,
            expected_runtime=expected_runtime,
            expected_options=expected_options,
            expected_protocol_sha256=expected_protocol_sha256,
            expected_config_sha256=expected_config_sha256,
        )

        model_info = self.receipt["model"]
        self.model_id = str(model_info["model_id"])
        self.weights_sha256 = str(model_info["weights_sha256"])
        self.original_backend = str(model_info["backend"])

    def _validate_receipt_structure(
        self,
        *,
        expected_case_id: str | None,
        expected_source_file_sha256: str | None,
        require_source_file_sha256: bool,
        expected_scale: int | None,
        expected_target_shape: tuple[int, int, int] | None,
        expected_model_id: str | None,
        expected_backend: str | None,
        expected_weights_sha256: str | None,
        expected_runtime: Mapping[str, Any] | None,
        expected_options: Mapping[str, Any] | None,
        expected_protocol_sha256: str | None,
        expected_config_sha256: str | None,
    ) -> None:
        r = self.receipt
        for section in ("source", "target", "model", "rois", "protocol", "generation_identity", "artifacts"):
            if not isinstance(r.get(section), Mapping):
                raise CheckpointError(f"Checkpoint receipt missing {section!r} metadata")

        if expected_case_id is not None and r.get("case_id") != expected_case_id:
            raise CheckpointError(
                f"Checkpoint case_id {r.get('case_id')!r} != expected {expected_case_id!r}"
            )

        src = r["source"]
        rec_src_file_sha = src.get("source_file_sha256")
        if require_source_file_sha256 and not rec_src_file_sha:
            raise CheckpointError("Checkpoint receipt missing required source_file_sha256")
        if expected_source_file_sha256 is not None and rec_src_file_sha != expected_source_file_sha256:
            raise CheckpointError(
                f"Checkpoint source_file_sha256 {rec_src_file_sha!r} != expected {expected_source_file_sha256!r}"
            )

        target = r["target"]
        if expected_scale is not None and target.get("scale") != int(expected_scale):
            raise CheckpointError(f"Checkpoint scale {target.get('scale')} != expected {expected_scale}")
        t_shape = target.get("target_shape")
        if not isinstance(t_shape, list) or len(t_shape) != 3:
            raise CheckpointError(f"Checkpoint invalid target_shape: {t_shape!r}")
        if expected_target_shape is not None and tuple(t_shape) != tuple(expected_target_shape):
            raise CheckpointError(
                f"Checkpoint target_shape {tuple(t_shape)} != expected {tuple(expected_target_shape)}"
            )

        model = r["model"]
        if expected_model_id is not None and model.get("model_id") != expected_model_id:
            raise CheckpointError(
                f"Checkpoint model_id {model.get('model_id')!r} != expected {expected_model_id!r}"
            )
        if expected_backend is not None and model.get("backend") != expected_backend:
            raise CheckpointError(
                f"Checkpoint model backend {model.get('backend')!r} != expected {expected_backend!r}"
            )
        if expected_weights_sha256 is not None and model.get("weights_sha256") != expected_weights_sha256:
            raise CheckpointError(
                f"Checkpoint weights_sha256 {model.get('weights_sha256')!r} != expected {expected_weights_sha256!r}"
            )
        if expected_runtime is not None:
            exp_rt_sha = canonical_json_sha256(dict(expected_runtime))
            if model.get("runtime_sha256") != exp_rt_sha:
                raise CheckpointError("Checkpoint model runtime metadata mismatch")
        if expected_options is not None:
            exp_opt_sha = canonical_json_sha256(dict(expected_options))
            if model.get("options_sha256") != exp_opt_sha:
                raise CheckpointError("Checkpoint model options mismatch")

        if self._expected_normalized_rois is not None:
            self.validate_normalized_rois(self._expected_normalized_rois)

        prot = r["protocol"]
        if expected_protocol_sha256 is not None and prot.get("protocol_sha256") != expected_protocol_sha256:
            raise CheckpointError("Checkpoint protocol_sha256 mismatch")
        if expected_config_sha256 is not None and prot.get("config_sha256") != expected_config_sha256:
            raise CheckpointError("Checkpoint config_sha256 mismatch")

        gen = r["generation_identity"]
        if not isinstance(gen.get("file_hashes"), Mapping) or not gen["file_hashes"]:
            raise CheckpointError("Checkpoint generation_identity missing original file_hashes")

        target_tuple = (int(t_shape[0]), int(t_shape[1]), int(t_shape[2]))
        _validate_artifact_entry(
            self.checkpoint_dir,
            r["artifacts"],
            key="raw_candidate",
            expected_role="raw_candidate",
            expected_shape=target_tuple,
        )
        _validate_artifact_entry(
            self.checkpoint_dir,
            r["artifacts"],
            key="bicubic_base",
            expected_role="bicubic_base",
            expected_shape=target_tuple,
        )

    def validate_normalized_rois(self, normalized_rois: Sequence[Mapping[str, Any]]) -> None:
        """Fail closed if caller ROIs differ from the checkpoint's bound normalized ROIs."""
        rois_list = [dict(r) for r in normalized_rois]
        actual_sha = canonical_json_sha256(rois_list)
        expected_sha = self.receipt["rois"].get("normalized_rois_sha256")
        if actual_sha != expected_sha:
            raise CheckpointError(
                f"Checkpoint normalized ROI mismatch ({actual_sha} != {expected_sha})"
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
        if case_id is not None and self.receipt.get("case_id") is not None and case_id != self.receipt.get("case_id"):
            raise CheckpointError(
                f"Checkpoint case_id {self.receipt.get('case_id')!r} != requested {case_id!r}"
            )
        if int(scale) != int(self.receipt["target"]["scale"]):
            raise CheckpointError(
                f"Checkpoint scale {self.receipt['target']['scale']} != requested {scale}"
            )
        if tuple(target_shape) != tuple(self.receipt["target"]["target_shape"]):
            raise CheckpointError(
                f"Checkpoint target_shape {tuple(self.receipt['target']['target_shape'])} != requested {tuple(target_shape)}"
            )

        src_meta = self.receipt["source"]
        if list(source_rgb.shape) != src_meta.get("source_shape"):
            raise CheckpointError(
                f"Checkpoint source_shape {src_meta.get('source_shape')} != {list(source_rgb.shape)}"
            )
        actual_src_pixel_sha = compute_rgb_pixel_sha256(source_rgb)
        if actual_src_pixel_sha != src_meta.get("source_pixel_sha256"):
            raise CheckpointError("Checkpoint source_pixel_sha256 mismatch")

        artifacts = self.receipt["artifacts"]
        raw_path, raw_entry = _validate_artifact_entry(
            self.checkpoint_dir,
            artifacts,
            key="raw_candidate",
            expected_role="raw_candidate",
            expected_shape=target_shape,
        )
        bic_path, bic_entry = _validate_artifact_entry(
            self.checkpoint_dir,
            artifacts,
            key="bicubic_base",
            expected_role="bicubic_base",
            expected_shape=target_shape,
        )

        # Verify caller's base_4x matches the exact persisted bicubic_base before mmap replay.
        if tuple(base_4x.shape) != tuple(target_shape):
            raise CheckpointError(f"base_4x shape {base_4x.shape} != target_shape {target_shape}")
        actual_bic_pixel_sha = compute_rgb_pixel_sha256(base_4x)
        if actual_bic_pixel_sha != bic_entry["pixel_sha256"]:
            raise CheckpointError("Checkpoint bicubic_base pixel SHA-256 does not match current base_4x")

        # Validate both .npy files thoroughly (header, extent, SHA-256, pixel SHA-256, mmap).
        _ = load_validated_npy_mmap(
            bic_path,
            expected_shape=target_shape,
            expected_file_sha256=bic_entry["sha256"],
            expected_pixel_sha256=bic_entry["pixel_sha256"],
            expected_role="bicubic_base",
        )
        raw_mmap = load_validated_npy_mmap(
            raw_path,
            expected_shape=target_shape,
            expected_file_sha256=raw_entry["sha256"],
            expected_pixel_sha256=raw_entry["pixel_sha256"],
            expected_role="raw_candidate",
        )

        evaluation_identity = capture_code_identity()
        if self._evaluation_context:
            evaluation_identity["context"] = dict(self._evaluation_context)

        extra: dict[str, Any] = {
            "inference_executed": False,
            "checkpoint_replayed": True,
            "checkpoint_dir": str(self.checkpoint_dir),
            "checkpoint_receipt_sha256": self.receipt_sha256,
            "original_backend": self.original_backend,
            "original_model": copy.deepcopy(self.receipt["model"]),
            "original_generation_identity": copy.deepcopy(self.receipt["generation_identity"]),
            "evaluation_identity": evaluation_identity,
            "source_file_sha256": src_meta.get("source_file_sha256"),
            "source_pixel_sha256": src_meta.get("source_pixel_sha256"),
            "normalized_rois_sha256": self.receipt["rois"]["normalized_rois_sha256"],
            "protocol_sha256": self.receipt["protocol"].get("protocol_sha256"),
            "config_sha256": self.receipt["protocol"].get("config_sha256"),
        }
        return raw_mmap, extra
