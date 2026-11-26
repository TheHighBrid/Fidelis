"""Fail-closed raw inference checkpoint verification and replay backend (F13 / #135)."""

from __future__ import annotations

import copy
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np

from fidelis.engine.checkpoints import (
    RAW_CHECKPOINT_RECEIPT_FILENAME,
    SCHEMA_VERSION,
    CheckpointError,
    CheckpointExpectations,
    canonical_json_sha256,
    capture_code_identity,
    compute_rgb_pixel_sha256,
    sha256_file,
)


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


def _validate_receipt_source_and_target(
    receipt: Mapping[str, Any],
    exp: CheckpointExpectations,
) -> tuple[int, int, int]:
    src = receipt["source"]
    rec_src_file_sha = src.get("source_file_sha256")
    if exp.require_source_file_sha256 and not rec_src_file_sha:
        raise CheckpointError("Checkpoint receipt missing required source_file_sha256")
    if exp.expected_source_file_sha256 is not None and rec_src_file_sha != exp.expected_source_file_sha256:
        raise CheckpointError(
            f"Checkpoint source_file_sha256 {rec_src_file_sha!r} != expected {exp.expected_source_file_sha256!r}"
        )

    target = receipt["target"]
    if exp.expected_scale is not None and target.get("scale") != int(exp.expected_scale):
        raise CheckpointError(f"Checkpoint scale {target.get('scale')} != expected {exp.expected_scale}")
    t_shape = target.get("target_shape")
    if not isinstance(t_shape, list) or len(t_shape) != 3:
        raise CheckpointError(f"Checkpoint invalid target_shape: {t_shape!r}")
    target_tuple = (int(t_shape[0]), int(t_shape[1]), int(t_shape[2]))
    if exp.expected_target_shape is not None and target_tuple != tuple(exp.expected_target_shape):
        raise CheckpointError(
            f"Checkpoint target_shape {target_tuple} != expected {tuple(exp.expected_target_shape)}"
        )
    return target_tuple


def _validate_receipt_model_and_protocol(
    receipt: Mapping[str, Any],
    exp: CheckpointExpectations,
) -> None:
    model = receipt["model"]
    checks = (
        (exp.expected_model_id, "model_id", "Checkpoint model_id"),
        (exp.expected_backend, "backend", "Checkpoint model backend"),
        (exp.expected_weights_sha256, "weights_sha256", "Checkpoint weights_sha256"),
    )
    for expected_val, key, label in checks:
        if expected_val is not None and model.get(key) != expected_val:
            raise CheckpointError(f"{label} {model.get(key)!r} != expected {expected_val!r}")
    if exp.expected_runtime is not None:
        if model.get("runtime_sha256") != canonical_json_sha256(dict(exp.expected_runtime)):
            raise CheckpointError("Checkpoint model runtime metadata mismatch")
    if exp.expected_options is not None:
        if model.get("options_sha256") != canonical_json_sha256(dict(exp.expected_options)):
            raise CheckpointError("Checkpoint model options mismatch")

    prot = receipt["protocol"]
    if exp.expected_protocol_sha256 is not None and prot.get("protocol_sha256") != exp.expected_protocol_sha256:
        raise CheckpointError("Checkpoint protocol_sha256 mismatch")
    if exp.expected_config_sha256 is not None and prot.get("config_sha256") != exp.expected_config_sha256:
        raise CheckpointError("Checkpoint config_sha256 mismatch")


def _load_receipt_json(receipt_path: Path) -> dict[str, Any]:
    if not receipt_path.is_file():
        raise CheckpointError(
            f"Incomplete or missing raw checkpoint: {receipt_path} does not exist"
        )
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CheckpointError(f"Malformed checkpoint receipt {receipt_path}: {exc}") from exc
    if not isinstance(receipt, Mapping) or receipt.get("schema_version") != SCHEMA_VERSION:
        raise CheckpointError(
            f"Unsupported or invalid checkpoint receipt schema in {receipt_path}"
        )
    return copy.deepcopy(dict(receipt))


class CheckpointRestorationBackend:
    """Explicit replay backend loading verified raw checkpoints without executing inference."""

    backend_name = "checkpoint_replay"

    def __init__(
        self,
        checkpoint_dir: str | Path,
        *,
        expectations: CheckpointExpectations | None = None,
        evaluation_context: Mapping[str, Any] | None = None,
        **legacy_expectations: Any,
    ) -> None:
        if expectations is not None and legacy_expectations:
            raise TypeError("Specify either expectations or individual expectation kwargs, not both")
        resolved_exp = expectations if expectations is not None else CheckpointExpectations.from_kwargs(legacy_expectations)

        self.checkpoint_dir = Path(checkpoint_dir)
        self.receipt_path = self.checkpoint_dir / RAW_CHECKPOINT_RECEIPT_FILENAME
        self.receipt = _load_receipt_json(self.receipt_path)
        self.receipt_sha256 = sha256_file(self.receipt_path)
        self._evaluation_context = dict(evaluation_context or {})

        self._validate_receipt_structure(resolved_exp)
        model_info = self.receipt["model"]
        self.model_id = str(model_info["model_id"])
        self.weights_sha256 = str(model_info["weights_sha256"])
        self.original_backend = str(model_info["backend"])

    def _validate_receipt_structure(self, exp: CheckpointExpectations) -> None:
        r = self.receipt
        for section in ("source", "target", "model", "rois", "protocol", "generation_identity", "artifacts"):
            if not isinstance(r.get(section), Mapping):
                raise CheckpointError(f"Checkpoint receipt missing {section!r} metadata")
        if exp.expected_case_id is not None and r.get("case_id") != exp.expected_case_id:
            raise CheckpointError(
                f"Checkpoint case_id {r.get('case_id')!r} != expected {exp.expected_case_id!r}"
            )

        target_tuple = _validate_receipt_source_and_target(r, exp)
        _validate_receipt_model_and_protocol(r, exp)
        if exp.expected_normalized_rois is not None:
            self.validate_normalized_rois(exp.expected_normalized_rois)

        gen = r["generation_identity"]
        if not isinstance(gen.get("file_hashes"), Mapping) or not gen["file_hashes"]:
            raise CheckpointError("Checkpoint generation_identity missing original file_hashes")

        for key in ("raw_candidate", "bicubic_base"):
            _validate_artifact_entry(
                self.checkpoint_dir,
                r["artifacts"],
                key=key,
                expected_role=key,
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

    def _verify_restore_inputs(
        self,
        source_rgb: np.ndarray,
        base_4x: np.ndarray,
        *,
        scale: int,
        target_shape: tuple[int, int, int],
        case_id: str | None,
    ) -> dict[str, Any]:
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
        if compute_rgb_pixel_sha256(source_rgb) != src_meta.get("source_pixel_sha256"):
            raise CheckpointError("Checkpoint source_pixel_sha256 mismatch")
        if tuple(base_4x.shape) != tuple(target_shape):
            raise CheckpointError(f"base_4x shape {base_4x.shape} != target_shape {target_shape}")
        return src_meta

    def _build_replay_extra(self, src_meta: Mapping[str, Any]) -> dict[str, Any]:
        evaluation_identity = capture_code_identity()
        if self._evaluation_context:
            evaluation_identity["context"] = dict(self._evaluation_context)
        return {
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

    def restore(
        self,
        source_rgb: np.ndarray,
        *,
        base_4x: np.ndarray,
        scale: int,
        target_shape: tuple[int, int, int],
        case_id: str | None = None,
    ) -> tuple[np.ndarray, dict[str, Any]]:
        src_meta = self._verify_restore_inputs(
            source_rgb, base_4x, scale=scale, target_shape=target_shape, case_id=case_id
        )
        artifacts = self.receipt["artifacts"]
        raw_path, raw_entry = _validate_artifact_entry(
            self.checkpoint_dir, artifacts, key="raw_candidate", expected_role="raw_candidate", expected_shape=target_shape
        )
        bic_path, bic_entry = _validate_artifact_entry(
            self.checkpoint_dir, artifacts, key="bicubic_base", expected_role="bicubic_base", expected_shape=target_shape
        )
        if compute_rgb_pixel_sha256(base_4x) != bic_entry["pixel_sha256"]:
            raise CheckpointError("Checkpoint bicubic_base pixel SHA-256 does not match current base_4x")

        load_validated_npy_mmap(
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
        return raw_mmap, self._build_replay_extra(src_meta)
