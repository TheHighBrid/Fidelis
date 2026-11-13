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
from tempfile import TemporaryFile
import uuid

import numpy as np

from fidelis.postprocess.regions import PROFILES, RegionBlend, _mask, _rgb, compose_regions
from fidelis.studio.brush import EDIT_FIELDS, apply_stripe, validate_strokes

from fidelis.studio.png import write_rgb_png  # Preserve the existing encoder import path.
from fidelis.studio.structure import measure_region, validate_regions

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

    def _render_into(self, artifacts, blend, output, *, verify=False):
        base = self._array(artifacts["base"], verify=verify)
        texture = self._array(artifacts["texture"], verify=verify)
        masks = {name: self._array(artifacts[name], verify=verify)
                 for name in MASK_NAMES if name in artifacts}
        rows = self._rows(base.shape[1])
        for y in range(0, base.shape[0], rows):
            stripe = slice(y, y + rows)
            output[stripe], _ = compose_regions(
                base[stripe], texture[stripe], blend=blend, output_dtype=output.dtype,
                **{name: mask[stripe] for name, mask in masks.items()})
        output.flush()

    def _render(self, artifacts, blend):
        shape = artifacts["base"]["shape"]
        path = self.root / "artifacts" / f"{uuid.uuid4().hex}.npy"
        output = np.lib.format.open_memmap(path, mode="w+", dtype=np.uint8, shape=tuple(shape))
        try:
            self._render_into(artifacts, blend, output)
        finally:
            del output
        return asdict(ImageArtifact(str(path.relative_to(self.root)), sha256(path),
                                    shape, "uint8", "sRGB-uint8", path.stat().st_size))

    @contextmanager
    def open_master16(self, job_id, expected_revision):
        """Recompose a saved revision at 16 bits with bounded stripe allocations."""
        with self._transaction() as db:
            manifest = self._read(db, job_id)
            if manifest["revision"] != expected_revision:
                raise RevisionConflict("Image revision changed; reopen the current job")
            artifacts = manifest["artifacts"]
            shape = tuple(artifacts["base"]["shape"])
            self._cleanup(db)
            self._check_budget(db, int(np.prod(shape)) * 2)
            with TemporaryFile(dir=self.root) as temp:
                output = np.memmap(temp, mode="w+", dtype=np.uint16, shape=shape)
                try:
                    self._render_into(artifacts, RegionBlend(**manifest["blend"]), output, verify=True)
                    yield output
                finally:
                    del output

    def get(self, job_id):
        with self._transaction() as db:
            return self._read(db, job_id)

    def list(self):
        with self._transaction() as db:
            return [json.loads(row[0]) for row in db.execute("SELECT manifest FROM jobs ORDER BY rowid DESC")]

    def reblend(self, job_id, *, expected_revision, blend, masks=None, strokes=None, lock_regions=None):
        if lock_regions is not None and (masks is not None or strokes is not None):
            raise ValueError("Apply structural locks in a separate revision")
        if strokes is not None:
            strokes = validate_strokes(strokes)
        if strokes and masks is not None:
            raise ValueError("Cannot replace masks and apply strokes in the same edit")
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
            if lock_regions is not None:
                lock_regions = validate_regions(lock_regions, width, height)
            estimate = height * width * 3 + 256
            if lock_regions:
                estimate += height * width * 4 + 256
            estimate += sum(mask.size * 4 + 256 for mask in (masks or {}).values())
            if strokes:
                estimate += len(EDIT_FIELDS) * (height * width * 4 + 256)
            self._cleanup(db)
            self._check_budget(db, estimate)
            try:
                if masks is not None:
                    # Supplied masks are a complete replacement, never an ambiguous merge.
                    artifacts = {key: value for key, value in artifacts.items() if key not in MASK_NAMES}
                    for name, mask in masks.items():
                        artifacts[name] = self._save(np.asarray(mask, dtype=np.float32), "mask-0-1")
                if strokes:
                    artifacts.update(self._paint(artifacts, strokes))
                if lock_regions:
                    artifacts["protected"] = self._lock_regions(artifacts, lock_regions, width, height)
                artifacts["master"] = self._render(artifacts, blend)
                manifest.update(revision=expected_revision + 1, blend=asdict(blend), artifacts=artifacts,
                                updated_at=datetime.now(timezone.utc).isoformat())
                if lock_regions:
                    manifest["last_structural_lock"] = {
                        "revision": expected_revision + 1, "rectangles": lock_regions,
                    }
                if strokes:
                    manifest["last_mask_edit"] = {"revision": expected_revision + 1, "strokes": strokes}
                db.execute("UPDATE jobs SET manifest=? WHERE id=?", (json.dumps(manifest), job_id))
                # Cleanup after UPDATE under the same transaction would delete old
                # files needed if commit fails. Leave garbage for the next operation.
                return manifest
            except BaseException:
                self._cleanup(db)
                raise

    def replace_texture(self, job_id, texture, *, expected_revision, candidate_recipe):
        texture = _rgb(texture, 'texture')
        with self._transaction() as db:
            manifest = self._read(db, job_id)
            if manifest['revision'] != expected_revision:
                raise RevisionConflict('Job changed while generation ran; generated texture remains available separately')
            if manifest['profile'] == 'packshot_strict':
                raise ValueError('Packshot Strict cannot accept a generated texture')
            if list(texture.shape) != manifest['artifacts']['base']['shape']:
                raise ValueError('Generated texture must use the exact base grid')
            artifacts = manifest['artifacts'].copy()
            for descriptor in artifacts.values():
                self._array(descriptor, verify=True)
            # Freeze JSON-compatible recipe before any files become visible.
            recipe = json.loads(json.dumps(candidate_recipe, allow_nan=False))
            self._cleanup(db)
            self._check_budget(db, texture.nbytes * 2 + 512)
            try:
                artifacts['texture'] = self._save(texture, 'sRGB-uint8')
                artifacts['master'] = self._render(artifacts, RegionBlend(**manifest['blend']))
                manifest.update(revision=expected_revision+1, artifacts=artifacts, candidate_recipe=recipe,
                                inference_executed=bool(recipe.get('inference_executed', False)),
                                updated_at=datetime.now(timezone.utc).isoformat())
                db.execute('UPDATE jobs SET manifest=? WHERE id=?', (json.dumps(manifest),job_id))
                return manifest
            except BaseException:
                self._cleanup(db)
                raise

    def stage_suggestion(self, job_id, scores, receipt, *, expected_revision,
                         threshold=.90, margin=.15, boundary=1):
        from fidelis.studio.suggestions import build_suggestion
        if type(expected_revision) is not int:
            raise ValueError('expected_revision must be an integer')
        with self._transaction() as db:
            manifest = self._read(db, job_id)
            if manifest['revision'] != expected_revision:
                raise RevisionConflict('Job changed; reload before staging a suggestion')
            if manifest['profile'] == 'packshot_strict':
                raise ValueError('Packshot Strict does not accept semantic texture suggestions')
            artifacts = manifest['artifacts'].copy()
            for descriptor in artifacts.values():
                self._array(descriptor, verify=True)
            low, record = build_suggestion(scores, receipt,
                            base_sha256=artifacts['base']['sha256'], dimensions=manifest['dimensions'],
                            threshold=threshold, margin=margin, boundary=boundary)
            width, height = manifest['dimensions']
            self._cleanup(db)
            self._check_budget(db, width*height*4*5 + 5*256)
            try:
                staged = self._suggestion_arrays(artifacts, low, width, height)
                artifacts = {key:value for key,value in artifacts.items() if not key.startswith('suggestion_')}
                artifacts.update(staged)
                record.update(id=uuid.uuid4().hex, status='staged', based_on_revision=expected_revision,
                              staged_revision=expected_revision+1)
                manifest.update(revision=expected_revision+1, artifacts=artifacts, mask_suggestion=record,
                                updated_at=datetime.now(timezone.utc).isoformat())
                db.execute('UPDATE jobs SET manifest=? WHERE id=?', (json.dumps(manifest),job_id))
                return manifest
            except BaseException:
                self._cleanup(db)
                raise

    def resolve_suggestion(self, job_id, *, expected_revision, accept):
        if type(expected_revision) is not int or type(accept) is not bool:
            raise ValueError('Expected an integer revision and boolean accept')
        with self._transaction() as db:
            manifest = self._read(db, job_id)
            if manifest['revision'] != expected_revision:
                raise RevisionConflict('Job changed; reopen before resolving a suggestion')
            record = manifest.get('mask_suggestion')
            if not record or record['status'] != 'staged':
                raise ValueError('No staged mask suggestion')
            if accept and record['staged_revision'] != expected_revision:
                raise RevisionConflict('Suggestion is stale after another edit; discard or import a new one')
            artifacts = manifest['artifacts'].copy()
            if accept:
                for descriptor in artifacts.values():
                    self._array(descriptor, verify=True)
            width, height = manifest['dimensions']
            self._cleanup(db)
            self._check_budget(db, width*height*(5*4+3)+6*256 if accept else 0)
            try:
                if accept:
                    artifacts.update(self._suggestion_arrays(artifacts, None, width, height, merge=True))
                    artifacts['master'] = self._render(artifacts, RegionBlend(**manifest['blend']))
                artifacts = {key:value for key,value in artifacts.items() if not key.startswith('suggestion_')}
                record.update(status='accepted' if accept else 'discarded', resolved_revision=expected_revision+1)
                manifest.update(revision=expected_revision+1, artifacts=artifacts,
                                updated_at=datetime.now(timezone.utc).isoformat())
                db.execute('UPDATE jobs SET manifest=? WHERE id=?', (json.dumps(manifest),job_id))
                return manifest
            except BaseException:
                self._cleanup(db)
                raise

    def _suggestion_arrays(self, artifacts, low, width, height, merge=False):
        from fidelis.studio.suggestions import FIELDS, fill_unclassified, upsample_stripe
        originals = {name:self._array(artifacts[name]) for name in MASK_NAMES if name in artifacts} if merge else {}
        proposed = {name:self._array(artifacts['suggestion_'+name]) for name in FIELDS} if merge else {}
        paths = {name:self.root/'artifacts'/f'{uuid.uuid4().hex}.npy' for name in FIELDS}
        outputs = {name:np.lib.format.open_memmap(path, mode='w+', dtype=np.float32,
                                                shape=(height,width)) for name,path in paths.items()}
        try:
            for y in range(0,height,self._rows(width)):
                end = min(height,y+self._rows(width))
                if merge:
                    stripe = fill_unclassified({name:array[y:end] for name,array in originals.items()},
                                                {name:array[y:end] for name,array in proposed.items()})
                else:
                    stripe = upsample_stripe(low,width,height,y,end)
                for name,array in outputs.items():
                    array[y:end] = stripe[name]
            for array in outputs.values():
                array.flush()
        finally:
            outputs.clear()
        return {('' if merge else 'suggestion_')+name:asdict(ImageArtifact(
                        str(path.relative_to(self.root)),sha256(path),[height,width],
                        'float32','mask-0-1',path.stat().st_size)) for name,path in paths.items()}

    def inspect_structure(self, job_id, *, expected_revision, regions, target):
        if target not in ("texture", "master"):
            raise ValueError("Compare the saved base with texture or master")
        with self._transaction() as db:
            job = self._read(db, job_id)
            if job["revision"] != expected_revision:
                raise RevisionConflict("Job changed; reload the current revision before inspecting")
            artifacts = job["artifacts"]
            base = self._array(artifacts["base"], verify=True)
            candidate = self._array(artifacts[target], verify=True)
            if candidate.shape != base.shape:
                raise ValueError("Comparison requires the exact saved base grid")
            height, width = base.shape[:2]
            regions = validate_regions(regions, width, height)
            return {
                "id": job_id,
                "revision": expected_revision,
                "base_sha256": artifacts["base"]["sha256"],
                "target": target,
                "target_sha256": artifacts[target]["sha256"],
                "regions": [measure_region(base, candidate, box, self._rows(width)) for box in regions],
            }

    def _lock_regions(self, artifacts, regions, width, height):
        previous = self._array(artifacts["protected"]) if "protected" in artifacts else None
        path = self.root / "artifacts" / f"{uuid.uuid4().hex}.npy"
        output = np.lib.format.open_memmap(path, mode="w+", dtype=np.float32, shape=(height, width))
        try:
            rows = self._rows(width)
            for start in range(0, height, rows):
                end = min(start + rows, height)
                output[start:end] = previous[start:end] if previous is not None else 0
                for x, y, w, h in regions:
                    top, bottom = max(start, y), min(end, y + h)
                    if top < bottom:
                        output[top:bottom, x:x + w] = 1.0
            output.flush()
        finally:
            del output
        return asdict(ImageArtifact(str(path.relative_to(self.root)), sha256(path),
                                    [height, width], "float32", "mask-0-1", path.stat().st_size))

    def _paint(self, artifacts, strokes):
        height, width = artifacts['base']['shape'][:2]
        original = {name: self._array(artifacts[name]) for name in EDIT_FIELDS if name in artifacts}
        paths = {name: self.root / 'artifacts' / f'{uuid.uuid4().hex}.npy' for name in EDIT_FIELDS}
        outputs = {name: np.lib.format.open_memmap(path, mode='w+', dtype=np.float32,
                                                  shape=(height, width)) for name, path in paths.items()}
        try:
            rows = self._rows(width)
            for y in range(0, height, rows):
                end = min(height, y + rows)
                fields = {name: np.array(original[name][y:end], copy=True) if name in original else
                          np.zeros((end-y, width), np.float32) for name in EDIT_FIELDS}
                apply_stripe(fields, strokes, width, height, y, end)
                for name, array in outputs.items():
                    array[y:end] = fields[name]
            for array in outputs.values():
                array.flush()
        finally:
            outputs.clear()
        return {name: asdict(ImageArtifact(str(path.relative_to(self.root)), sha256(path),
                        [height, width], 'float32', 'mask-0-1', path.stat().st_size))
                for name, path in paths.items()}

    def mask_data(self, job_id, expected_revision, pixel_limit=1_000_000):
        import base64
        with self._transaction() as db:
            manifest = self._read(db, job_id)
            if manifest['revision'] != expected_revision:
                raise RevisionConflict('Mask revision changed; reopen the job')
            width, height = manifest['dimensions']
            stride = max(1, int(np.ceil(np.sqrt(width * height / pixel_limit))))
            shape = ((height + stride - 1)//stride, (width + stride - 1)//stride)
            layers = {}
            for name in ('skin', 'hair', 'fabric', 'protected'):
                if name in manifest['artifacts']:
                    mask = self._array(manifest['artifacts'][name], verify=True)[::stride, ::stride]
                    encoded = np.clip(np.rint(mask * 255), 0, 255).astype(np.uint8).tobytes()
                    layers[name] = base64.b64encode(encoded).decode('ascii')
            return {'width': shape[1], 'height': shape[0], 'layers': layers}

    def mask_preview(self, job_id, expected_revision, pixel_limit=1_000_000, *, suggestion=False):
        with self._transaction() as db:
            manifest = self._read(db, job_id)
            if manifest['revision'] != expected_revision:
                raise RevisionConflict('Mask revision changed; reopen the job')
            if suggestion and manifest.get('mask_suggestion',{}).get('status') != 'staged':
                raise ValueError('No staged suggestion preview')
            width, height = manifest['dimensions']
            stride = max(1, int(np.ceil(np.sqrt(width * height / pixel_limit))))
            shape = ((height + stride - 1)//stride, (width + stride - 1)//stride)
            preview = np.zeros((*shape, 4), np.float32)
            colors = {'skin': (239, 90, 90), 'hair': (241, 196, 80),
                      'fabric': (91, 202, 132), 'protected': (92, 145, 255)}
            for name, color in colors.items():
                artifact_name = ('suggestion_' if suggestion else '')+name
                if artifact_name not in manifest['artifacts']:
                    continue
                mask = self._array(manifest['artifacts'][artifact_name], verify=True)[::stride, ::stride]
                opacity = mask * .6
                preview[...,:3] = preview[...,:3] * (1-opacity[...,None]) + np.array(color) * opacity[...,None]
                preview[...,3] += (255 - preview[...,3]) * opacity
            # Convert accumulated premultiplied RGB to straight alpha for PNG.
            alpha = preview[...,3:4] / 255
            preview[...,:3] = np.divide(preview[...,:3], alpha, out=np.zeros_like(preview[...,:3]), where=alpha > 0)
            return np.clip(np.rint(preview), 0, 255).astype(np.uint8)

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
