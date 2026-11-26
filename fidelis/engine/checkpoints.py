"""Resumable raw inference checkpoints (F13 / #135).

Persists unguarded raw model output (`raw_candidate.npy`) and the exact
paired 4x bicubic reference (`bicubic_base.npy`) immediately after inference
and exact-shape validation, before texture guard composition, drift screening,
or evaluation.  The receipt (`checkpoint_receipt.json`) is atomically published
last so partial writes never pass verification.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess  # nosec B404
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields
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
    "fidelis/engine/checkpoint_replay.py",
    "fidelis/studio/audition.py",
    "fidelis/postprocess/regions.py",
    "fidelis/postprocess/roi_protection.py",
)


class CheckpointError(ValueError):
    """Raised when a raw generation checkpoint is missing, partial, tampered, or mismatched."""


@dataclass(frozen=True)
class RawCheckpointMetadata:
    """Bound generation provenance and target metadata for a raw checkpoint."""

    scale: int
    target_shape: tuple[int, int, int]
    model_id: str
    backend: str
    weights_sha256: str
    normalized_rois: Sequence[Mapping[str, Any]] = ()
    case_id: str | None = None
    source_file_sha256: str | None = None
    source_path: str | Path | None = None
    model_runtime: Mapping[str, Any] | None = None
    model_options: Mapping[str, Any] | None = None
    protocol_sha256: str | None = None
    config_sha256: str | None = None
    extra_provenance: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class RawCheckpointContext:
    """Optional provenance/protocol context bound by make_raw_checkpoint_callback."""

    source_file_sha256: str | None = None
    source_path: str | Path | None = None
    model_runtime: Mapping[str, Any] | None = None
    model_options: Mapping[str, Any] | None = None
    protocol_sha256: str | None = None
    config_sha256: str | None = None
    out_record: dict[str, Any] | None = None

    @classmethod
    def from_kwargs(cls, kwargs: Mapping[str, Any]) -> RawCheckpointContext:
        valid = {f.name for f in fields(cls)}
        unknown = sorted(set(kwargs) - valid)
        if unknown:
            raise TypeError(f"Unexpected keyword argument(s): {', '.join(unknown)}")
        return cls(**dict(kwargs))


@dataclass(frozen=True)
class CheckpointExpectations:
    """Expected identity and artifact parameters checked during checkpoint replay."""

    expected_case_id: str | None = None
    expected_source_file_sha256: str | None = None
    require_source_file_sha256: bool = False
    expected_scale: int | None = None
    expected_target_shape: tuple[int, int, int] | None = None
    expected_model_id: str | None = None
    expected_backend: str | None = None
    expected_weights_sha256: str | None = None
    expected_runtime: Mapping[str, Any] | None = None
    expected_options: Mapping[str, Any] | None = None
    expected_normalized_rois: Sequence[Mapping[str, Any]] | None = None
    expected_protocol_sha256: str | None = None
    expected_config_sha256: str | None = None

    @classmethod
    def from_kwargs(cls, kwargs: Mapping[str, Any]) -> CheckpointExpectations:
        valid = {f.name for f in fields(cls)}
        unknown = sorted(set(kwargs) - valid)
        if unknown:
            raise TypeError(f"Unexpected keyword argument(s): {', '.join(unknown)}")
        return cls(**dict(kwargs))


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


def _query_git_state(repo_root: Path) -> tuple[str | None, bool | None]:
    if not Path("/usr/bin/git").is_file():
        return None, None
    try:
        code_commit = subprocess.run(  # nosec B603
            ["/usr/bin/git", "rev-parse", "HEAD"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.strip()
        working_tree_dirty = bool(
            subprocess.run(  # nosec B603
                ["/usr/bin/git", "status", "--porcelain"],
                cwd=repo_root,
                check=True,
                capture_output=True,
                text=True,
                timeout=5,
            ).stdout.strip()
        )
        return code_commit, working_tree_dirty
    except (OSError, subprocess.SubprocessError):
        return None, None


def capture_code_identity(extra_paths: Sequence[str | Path] = ()) -> dict[str, Any]:
    """Record current repository commit, dirty flag, and core file SHA-256 digests."""
    repo_root = Path(__file__).resolve().parents[2]
    code_commit, working_tree_dirty = _query_git_state(repo_root)

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


def _resolve_source_file_sha(metadata: RawCheckpointMetadata) -> str | None:
    if metadata.source_file_sha256 is not None:
        return metadata.source_file_sha256
    if metadata.source_path is None:
        return None
    sp = Path(metadata.source_path)
    if not sp.is_file():
        raise CheckpointError(f"Source file missing when saving checkpoint: {sp}")
    return sha256_file(sp)


def _build_model_metadata(metadata: RawCheckpointMetadata) -> dict[str, Any]:
    runtime_dict = dict(metadata.model_runtime or {})
    options_dict = dict(metadata.model_options or {})
    return {
        "model_id": str(metadata.model_id),
        "backend": str(metadata.backend),
        "weights_sha256": str(metadata.weights_sha256),
        "runtime": runtime_dict,
        "runtime_sha256": canonical_json_sha256(runtime_dict),
        "options": options_dict,
        "options_sha256": canonical_json_sha256(options_dict),
        "extra_provenance": dict(metadata.extra_provenance or {}),
    }


def _build_checkpoint_receipt(
    *,
    source_rgb: np.ndarray,
    metadata: RawCheckpointMetadata,
    resolved_source_file_sha: str | None,
    raw_meta: dict[str, Any],
    bic_meta: dict[str, Any],
) -> dict[str, Any]:
    norm_rois_list = [dict(r) for r in metadata.normalized_rois]
    return {
        "schema_version": SCHEMA_VERSION,
        "case_id": metadata.case_id,
        "source": {
            "source_file_sha256": resolved_source_file_sha,
            "source_pixel_sha256": compute_rgb_pixel_sha256(source_rgb),
            "source_shape": [int(v) for v in source_rgb.shape],
        },
        "target": {
            "scale": int(metadata.scale),
            "target_shape": [int(v) for v in metadata.target_shape],
        },
        "model": _build_model_metadata(metadata),
        "rois": {
            "roi_space": "target",
            "normalized_rois": norm_rois_list,
            "normalized_rois_sha256": canonical_json_sha256(norm_rois_list),
        },
        "protocol": {
            "protocol_sha256": metadata.protocol_sha256,
            "config_sha256": metadata.config_sha256,
        },
        "generation_identity": capture_code_identity(),
        "artifacts": {
            "raw_candidate": raw_meta,
            "bicubic_base": bic_meta,
        },
    }


def save_raw_checkpoint(
    checkpoint_dir: str | Path,
    *,
    source_rgb: np.ndarray,
    base_4x: np.ndarray,
    raw_candidate: np.ndarray,
    metadata: RawCheckpointMetadata | None = None,
    **legacy_metadata: Any,
) -> dict[str, Any]:
    """Persist raw_candidate.npy and bicubic_base.npy, then atomically publish the receipt last."""
    resolved_meta = metadata if metadata is not None else RawCheckpointMetadata(**legacy_metadata)
    if metadata is not None and legacy_metadata:
        raise TypeError("Specify either metadata or individual metadata fields, not both")

    dest_dir = Path(checkpoint_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    target_shape = tuple(resolved_meta.target_shape)
    if tuple(raw_candidate.shape) != target_shape:
        raise CheckpointError(
            f"raw_candidate shape {raw_candidate.shape} does not match target_shape {target_shape}"
        )
    if tuple(base_4x.shape) != target_shape:
        raise CheckpointError(
            f"base_4x shape {base_4x.shape} does not match target_shape {target_shape}"
        )

    resolved_source_file_sha = _resolve_source_file_sha(resolved_meta)
    raw_meta = _write_npy_atomic(dest_dir / RAW_CANDIDATE_FILENAME, raw_candidate)
    raw_meta["role"] = "raw_candidate"
    bic_meta = _write_npy_atomic(dest_dir / BICUBIC_BASE_FILENAME, base_4x)
    bic_meta["role"] = "bicubic_base"

    receipt = _build_checkpoint_receipt(
        source_rgb=source_rgb,
        metadata=resolved_meta,
        resolved_source_file_sha=resolved_source_file_sha,
        raw_meta=raw_meta,
        bic_meta=bic_meta,
    )
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
    context: RawCheckpointContext | None = None,
    **legacy_context: Any,
):
    """Build a RestorationRunner raw-checkpoint callback bound to the generation context."""
    ctx = context if context is not None else RawCheckpointContext.from_kwargs(legacy_context)
    if context is not None and legacy_context:
        raise TypeError("Specify either context or individual context keyword arguments, not both")

    def _callback(payload: Mapping[str, Any]) -> None:
        metadata = RawCheckpointMetadata(
            scale=int(payload["scale"]),
            target_shape=tuple(payload["target_shape"]),
            model_id=str(payload["model_id"]),
            backend=str(payload["backend"]),
            weights_sha256=str(payload["weights_sha256"]),
            normalized_rois=payload.get("normalized_rois") or (),
            case_id=payload.get("case_id"),
            source_file_sha256=ctx.source_file_sha256,
            source_path=ctx.source_path,
            model_runtime=ctx.model_runtime,
            model_options=ctx.model_options,
            protocol_sha256=ctx.protocol_sha256,
            config_sha256=ctx.config_sha256,
            extra_provenance=payload.get("extra") or {},
        )
        saved = save_raw_checkpoint(
            checkpoint_dir,
            source_rgb=payload["source_rgb"],
            base_4x=payload["base_4x"],
            raw_candidate=payload["raw_candidate"],
            metadata=metadata,
        )
        if ctx.out_record is not None:
            ctx.out_record.clear()
            ctx.out_record.update(saved)

    return _callback
