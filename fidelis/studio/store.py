"""Versioned disk-backed image artifacts and bounded regional composition.

SQLite serializes commits across processes. Candidate files become visible only
when their manifest commits; startup removes abandoned files under that lock.
"""
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import struct
import uuid
import zlib

import numpy as np

from fidelis.postprocess.regions import PROFILES, RegionBlend, _mask, _rgb, compose_regions

MASK_NAMES = {"skin", "hair", "fabric", "protected", "confidence", "edge_guard"}


class BudgetExceeded(ValueError):
    pass


class RevisionConflict(ValueError):
    pass


def sha256(path):
    hasher = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


@dataclass(frozen=True)
class ImageArtifact:
    path: str
    sha256: str
    shape: list
    dtype: str
    encoding: str
    bytes: int


class JobStore:
    SCHEMA_VERSION = 1

    def __init__(self, root, *, disk_budget=2 * 1024**3,
                 workspace_budget=32 * 1024**2, max_pixels=40_000_000):
        for name, value in (("disk_budget", disk_budget), ("workspace_budget", workspace_budget),
                            ("max_pixels", max_pixels)):
            if not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.disk_budget = disk_budget
        self.workspace_budget = workspace_budget
        self.max_pixels = max_pixels
        with self._transaction() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, self.SCHEMA_VERSION):
                raise ValueError(f"Unsupported workspace schema {version}")
            db.execute("CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, manifest TEXT NOT NULL)")
            db.execute(f"PRAGMA user_version={self.SCHEMA_VERSION}")
            self._cleanup(db)

    @contextmanager
    def _transaction(self):
        db = sqlite3.connect(self.root / "jobs.sqlite3", timeout=30)
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def _cleanup(self, db):
        referenced = set()
        for (raw,) in db.execute("SELECT manifest FROM jobs"):
            manifest = json.loads(raw)
            referenced.update(item["path"] for item in manifest["artifacts"].values())
        directory = self.root / "artifacts"
        directory.mkdir(exist_ok=True)
        for path in directory.glob("*.npy"):
            if str(path.relative_to(self.root)) not in referenced:
                path.unlink()

    def _path(self, descriptor):
        path = (self.root / descriptor["path"]).resolve()
        if not path.is_relative_to(self.root / "artifacts") or path.suffix != ".npy":
            raise ValueError("Invalid artifact path")
        return path

    def _array(self, descriptor, verify=False):
        path = self._path(descriptor)
        if verify and sha256(path) != descriptor["sha256"]:
            raise ValueError("Artifact checksum mismatch")
        arr = np.load(path, mmap_mode="r", allow_pickle=False)
        if list(arr.shape) != descriptor["shape"] or str(arr.dtype) != descriptor["dtype"]:
            raise ValueError("Artifact contract mismatch")
        return arr

    def _save(self, array, encoding):
        path = self.root / "artifacts" / f"{uuid.uuid4().hex}.npy"
        np.save(path, array, allow_pickle=False)
        return asdict(ImageArtifact(str(path.relative_to(self.root)), sha256(path),
                                   list(array.shape), str(array.dtype), encoding, path.stat().st_size))

    @staticmethod
    def _read(db, job_id):
        if not re.fullmatch(r"[0-9a-f]{32}", job_id):
            raise KeyError("Unknown job")
        row = db.execute("SELECT manifest FROM jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            raise KeyError("Unknown job")
        manifest = json.loads(row[0])
        if manifest.get("schema_version") != 1:
            raise ValueError("Unsupported job manifest version")
        return manifest

    def _used(self, db, excluding=None):
        total = 0
        for job_id, raw in db.execute("SELECT id,manifest FROM jobs"):
            if job_id != excluding:
                total += sum(item["bytes"] for item in json.loads(raw)["artifacts"].values())
        return total

    def _check_budget(self, db, additional, excluding=None):
        if self._used(db, excluding) + additional > self.disk_budget:
            raise BudgetExceeded("Workspace storage budget exceeded; delete an old job or raise the limit")
        # Candidate revisions coexist with old artifacts until commit. Bound peak,
        # not just the eventual logical size. SQLite journal overhead is separate.
        physical = sum(path.stat().st_size for path in (self.root / "artifacts").glob("*.npy"))
        if physical + additional > self.disk_budget:
            raise BudgetExceeded("Insufficient storage headroom for an atomic revision")

    def create(self, base, texture, *, masks=None, blend=RegionBlend(), label="Untitled", profile="luxury_apparel"):
        if profile not in PROFILES:
            raise ValueError("Unknown profile")
        if profile == "packshot_strict" and any(getattr(blend, key) != 0 for key in ("skin", "hair", "fabric")):
            raise ValueError("packshot_strict does not allow generated blend")
        base, texture = _rgb(base, "base"), _rgb(texture, "texture")
        if base.shape != texture.shape:
            raise ValueError("Passes must have identical dimensions")
        height, width = base.shape[:2]
        if height * width > self.max_pixels:
            raise BudgetExceeded("Image exceeds configured pixel limit")
        masks = {} if masks is None else masks
        self._validate_masks(masks, (height, width))
        masks = {name: np.asarray(mask) for name, mask in masks.items()}
        # npy headers fit inside 256 bytes for these fixed RGB/mask shapes.
        estimate = base.nbytes * 3 + sum(mask.size * 4 for mask in masks.values())
        estimate += (3 + len(masks)) * 256
        self._rows(width)
        with self._transaction() as db:
            self._cleanup(db)
            self._check_budget(db, estimate)
            try:
                artifacts = {"base": self._save(base, "sRGB-uint8"),
                             "texture": self._save(texture, "sRGB-uint8")}
                for name, mask in masks.items():
                    artifacts[name] = self._save(np.asarray(mask, dtype=np.float32), "mask-0-1")
                artifacts["master"] = self._render(artifacts, blend)
                manifest = {"schema_version": 1, "id": uuid.uuid4().hex, "revision": 1,
                            "label": str(label)[:160], "profile": profile, "dimensions": [width, height],
                            "blend": asdict(blend), "artifacts": artifacts,
                            "inference_executed": False, "provenance": "unsigned_execution_record",
                            "created_at": datetime.now(timezone.utc).isoformat(),
                            "candidate_recipe": {"schema_version": 1, "origin": "externally_supplied",
                                                 "backend": None, "seed": None}}
                db.execute("INSERT INTO jobs VALUES (?,?)", (manifest["id"], json.dumps(manifest)))
                return manifest
            except BaseException:
                self._cleanup(db)
                raise

    @staticmethod
    def _validate_masks(masks, shape):
        unknown = set(masks) - MASK_NAMES
        if unknown:
            raise ValueError(f"Unknown mask names: {sorted(unknown)}")
        for name, mask in masks.items():
            _mask(mask, shape, name)

    def _rows(self, width):
        # Conservative allocation allowance for masks, lookup arrays, float transfer
        # intermediates and output. Excludes mapped disk pages and codec buffers.
        rows = self.workspace_budget // (width * 256)
        if rows < 1:
            raise BudgetExceeded("Composition workspace cannot fit one scanline")
        return min(256, rows)

    def _render(self, artifacts, blend):
        base, texture = self._array(artifacts["base"]), self._array(artifacts["texture"])
        masks = {name: self._array(artifacts[name]) for name in MASK_NAMES if name in artifacts}
        path = self.root / "artifacts" / f"{uuid.uuid4().hex}.npy"
        output = np.lib.format.open_memmap(path, mode="w+", dtype=np.uint8, shape=base.shape)
        try:
            rows = self._rows(base.shape[1])
            for y in range(0, base.shape[0], rows):
                stripe = slice(y, y + rows)
                output[stripe], _ = compose_regions(base[stripe], texture[stripe], blend=blend,
                                                    **{name: mask[stripe] for name, mask in masks.items()})
            output.flush()
        finally:
            del output
        return asdict(ImageArtifact(str(path.relative_to(self.root)), sha256(path),
                                    list(base.shape), "uint8", "sRGB-uint8", path.stat().st_size))

    def get(self, job_id):
        with self._transaction() as db:
            return self._read(db, job_id)

    def list(self):
        with self._transaction() as db:
            return [json.loads(row[0]) for row in db.execute("SELECT manifest FROM jobs ORDER BY rowid DESC")]

    def reblend(self, job_id, *, expected_revision, blend, masks=None):
        if not isinstance(expected_revision, int):
            raise ValueError("expected_revision must be an integer")
        with self._transaction() as db:
            manifest = self._read(db, job_id)
            if manifest["revision"] != expected_revision:
                raise RevisionConflict("Job changed; reload the current revision before saving")
            if manifest.get("profile") == "packshot_strict" and any(
                    getattr(blend, key) != 0 for key in ("skin", "hair", "fabric")):
                raise ValueError("packshot_strict does not allow generated blend")
            artifacts = manifest["artifacts"].copy()
            for descriptor in artifacts.values():
                self._array(descriptor, verify=True)
            height, width = artifacts["base"]["shape"][:2]
            if masks is not None:
                self._validate_masks(masks, (height, width))
                masks = {name: np.asarray(mask) for name, mask in masks.items()}
            estimate = height * width * 3 + 256
            estimate += sum(mask.size * 4 + 256 for mask in (masks or {}).values())
            self._cleanup(db)
            self._check_budget(db, estimate)
            try:
                if masks is not None:
                    # Supplied masks are a complete replacement, never an ambiguous merge.
                    artifacts = {key: value for key, value in artifacts.items() if key not in MASK_NAMES}
                    for name, mask in masks.items():
                        artifacts[name] = self._save(np.asarray(mask, dtype=np.float32), "mask-0-1")
                artifacts["master"] = self._render(artifacts, blend)
                manifest.update(revision=expected_revision + 1, blend=asdict(blend), artifacts=artifacts,
                                updated_at=datetime.now(timezone.utc).isoformat())
                db.execute("UPDATE jobs SET manifest=? WHERE id=?", (json.dumps(manifest), job_id))
                # Cleanup after UPDATE under the same transaction would delete old
                # files needed if commit fails. Leave garbage for the next operation.
                return manifest
            except BaseException:
                self._cleanup(db)
                raise

    def delete(self, job_id):
        with self._transaction() as db:
            self._read(db, job_id)
            db.execute("DELETE FROM jobs WHERE id=?", (job_id,))
        with self._transaction() as db:
            self._cleanup(db)

    @contextmanager
    def open_array(self, job_id, role, expected_revision=None):
        # Keep the transaction open while a response is encoded; a revision/delete
        # from another worker cannot remove the mapped file mid-response.
        with self._transaction() as db:
            manifest = self._read(db, job_id)
            if expected_revision is not None and manifest["revision"] != expected_revision:
                raise RevisionConflict("Image revision changed; reopen the current job")
            if role not in manifest["artifacts"]:
                raise KeyError("Unknown artifact")
            arr = self._array(manifest["artifacts"][role], verify=True)
            try:
                yield arr
            finally:
                del arr


def write_rgb_png(array, stream):
    """Encode uint8 RGB scanlines without building a full-frame Pillow copy."""
    _rgb(array, "PNG image")
    def chunk(kind, data):
        stream.write(struct.pack(">I", len(data)))
        stream.write(kind)
        stream.write(data)
        stream.write(struct.pack(">I", zlib.crc32(data, zlib.crc32(kind)) & 0xffffffff))
    stream.write(b"\x89PNG\r\n\x1a\n")
    chunk(b"IHDR", struct.pack(">IIBBBBB", array.shape[1], array.shape[0], 8, 2, 0, 0, 0))
    chunk(b"sRGB", b"\x00")
    compressor = zlib.compressobj(6)
    for row in array:
        encoded = compressor.compress(b"\x00" + row.tobytes())
        if encoded:
            chunk(b"IDAT", encoded)
    chunk(b"IDAT", compressor.flush())
    chunk(b"IEND", b"")
