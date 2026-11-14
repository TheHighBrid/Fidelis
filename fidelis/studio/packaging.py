"""Release archive auditing and durable workspace upgrade/rollback protection (F15 / MEL-69).

Verifies that packaged archives include all intended Studio, postprocess, and
evaluation modules while excluding local user workspaces (`.cache`), secrets,
and build artifacts. Also provides deterministic workspace snapshot, verification,
and atomic rollback for `JobStore` (`jobs.sqlite3` + `artifacts/*.npy`) and
`GenerationRunStore` (`runs/*.json`) across version upgrades and rollbacks.
"""

from __future__ import annotations

import fnmatch
import gzip
import hashlib
import json
import os
import shutil
import sqlite3
import tarfile
import tempfile
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence


SCHEMA_VERSION = "fidelis.packaging.v1"

REQUIRED_ARCHIVE_PATHS: tuple[str, ...] = (
    "bin/fidelis",
    "requirements.txt",
    "requirements-studio.txt",
    "Dockerfile",
    "docker-compose.yml",
    ".dockerignore",
    "scripts/web-ui.py",
    "scripts/backend-doctor.py",
    "scripts/reblend-regions.py",
    "scripts/benchmark-corpus.py",
    "scripts/mask-suggestion.py",
    "scripts/structural-roi.py",
    "scripts/export-studio-batch.py",
    "scripts/audit-model-provenance.py",
    "scripts/worker-preflight.py",
    "scripts/screen-roi-drift.py",
    "scripts/export-master.py",
    "scripts/run-comparators.py",
    "scripts/evaluate-quality-acceptance.py",
    "scripts/batch-run.py",
    "scripts/verify-upgrade-rollback.py",
    "scripts/audit-release-readiness.py",
    "scripts/package-release.sh",
    "scripts/package-offline-bundle.sh",
    "fidelis/__init__.py",
    "fidelis/postprocess/__init__.py",
    "fidelis/postprocess/regions.py",
    "fidelis/postprocess/color_fix.py",
    "fidelis/postprocess/roi_protection.py",
    "fidelis/postprocess/managed_export.py",
    "fidelis/studio/__init__.py",
    "fidelis/studio/store.py",
    "fidelis/studio/brush.py",
    "fidelis/studio/http.py",
    "fidelis/studio/studio.html",
    "fidelis/studio/editor.js",
    "fidelis/studio/inspection.py",
    "fidelis/studio/inspection.js",
    "fidelis/studio/comfy.py",
    "fidelis/studio/generation.py",
    "fidelis/studio/capabilities.py",
    "fidelis/studio/provenance.py",
    "fidelis/studio/worker_preflight.py",
    "fidelis/studio/suggestions.py",
    "fidelis/studio/segformer.py",
    "fidelis/studio/structure.py",
    "fidelis/studio/png.py",
    "fidelis/studio/batch.py",
    "fidelis/studio/packaging.py",
    "fidelis/studio/release_readiness.py",
    "fidelis/eval/__init__.py",
    "fidelis/eval/corpus_manifest.py",
    "fidelis/eval/pipeline_metrics.py",
    "fidelis/eval/benchmark_suite.py",
    "fidelis/eval/comparators.py",
    "fidelis/eval/quality_acceptance.py",
    "config/photo-candidates.tsv",
    "config/model-provenance-v1.json",
    "config/worker-preflight-policy-v1.json",
    "config/benchmark/protocol-v1.json",
    "config/benchmark/slots-v1.json",
    "config/benchmark/inventory-v1.json",
)

FORBIDDEN_ARCHIVE_PREFIXES: tuple[str, ...] = (
    ".git/",
    ".venv/",
    ".cache/",
    ".fidelis/",
    "dist/",
    "runtime/",
    "models/",
    "experiments/eval_crops/audition_",
    "experiments/eval_crops/web_audition/",
    "experiments/self_improvement/outputs/",
    "experiments/eval_corpus/",
)

FORBIDDEN_ARCHIVE_SEGMENTS: tuple[str, ...] = (
    "__pycache__",
    ".DS_Store",
)

FORBIDDEN_ARCHIVE_SUFFIXES: tuple[str, ...] = (
    ".pyc",
    ".pyo",
    ".pyd",
    ".apk",
)


def is_excluded_release_path(rel_path: str) -> bool:
    """Return True when a repository-relative path should be excluded from release archives."""
    norm = rel_path.replace("\\", "/").strip("/")
    if not norm or norm == ".":
        return False
    if norm == "config/release-candidate-v1.json":
        return True
    for prefix in FORBIDDEN_ARCHIVE_PREFIXES:
        stem = prefix.rstrip("/")
        if norm == stem or norm.startswith(prefix):
            return True
    parts = norm.split("/")
    if any(seg in FORBIDDEN_ARCHIVE_SEGMENTS or seg.startswith("._") for seg in parts):
        return True
    if any(norm.endswith(sfx) for sfx in FORBIDDEN_ARCHIVE_SUFFIXES):
        return True
    base = parts[-1]
    if base == ".env" or (base.startswith(".env.") and base != ".env.example"):
        return True
    if fnmatch.fnmatch(base, "*.old.*") or fnmatch.fnmatch(base, "fidelis-tile_*"):
        return True
    return False


def _iter_deterministic_entries(
    source_dir: Path,
    *,
    exclude_fn: Callable[[str], bool] | None = None,
) -> list[tuple[str, Path]]:
    root = source_dir.resolve()
    entries: list[tuple[str, Path]] = []
    for dirpath, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
        cur_dir = Path(dirpath)
        rel_dir = "" if cur_dir == root else cur_dir.relative_to(root).as_posix()

        kept_dirs: list[str] = []
        for dname in sorted(dirnames):
            rel_sub = f"{rel_dir}/{dname}".lstrip("/")
            if exclude_fn is not None and exclude_fn(rel_sub):
                continue
            kept_dirs.append(dname)
            entries.append((rel_sub, cur_dir / dname))
        dirnames[:] = kept_dirs

        for fname in sorted(filenames):
            rel_file = f"{rel_dir}/{fname}".lstrip("/")
            if exclude_fn is not None and exclude_fn(rel_file):
                continue
            entries.append((rel_file, cur_dir / fname))

    entries.sort(key=lambda item: item[0])
    return entries


def create_deterministic_tar_gz(
    source_dir: str | Path,
    output_path: str | Path,
    *,
    arcname_prefix: str = "",
    exclude_fn: Callable[[str], bool] | None = is_excluded_release_path,
) -> str:
    """Create a reproducible `.tar.gz` archive with fixed timestamps, permissions, and member order."""
    src_root = Path(source_dir).resolve()
    out_file = Path(output_path).resolve()
    out_file.parent.mkdir(parents=True, exist_ok=True)
    prefix = arcname_prefix.strip("/")

    entries = _iter_deterministic_entries(src_root, exclude_fn=exclude_fn)
    with out_file.open("wb") as raw_fh:
        with gzip.GzipFile(
            filename="", mode="wb", fileobj=raw_fh, compresslevel=9, mtime=0
        ) as gz_fh:
            with tarfile.open(
                mode="w|", fileobj=gz_fh, format=tarfile.GNU_FORMAT
            ) as tf:
                if prefix:
                    root_info = tarfile.TarInfo(name=prefix)
                    root_info.type = tarfile.DIRTYPE
                    root_info.mode = 0o755
                    root_info.mtime = 0
                    root_info.uid = 0
                    root_info.gid = 0
                    root_info.uname = ""
                    root_info.gname = ""
                    tf.addfile(root_info)
                for rel_path, full_path in entries:
                    arcname = f"{prefix}/{rel_path}" if prefix else rel_path
                    st = full_path.lstat()
                    info = tarfile.TarInfo(name=arcname)
                    info.mtime = 0
                    info.uid = 0
                    info.gid = 0
                    info.uname = ""
                    info.gname = ""
                    if full_path.is_symlink():
                        info.type = tarfile.SYMTYPE
                        info.mode = 0o777
                        info.linkname = os.readlink(full_path)
                        tf.addfile(info)
                    elif full_path.is_dir():
                        info.type = tarfile.DIRTYPE
                        info.mode = 0o755
                        info.size = 0
                        tf.addfile(info)
                    elif full_path.is_file():
                        info.type = tarfile.REGTYPE
                        info.mode = 0o755 if os.access(full_path, os.X_OK) else 0o644
                        info.size = st.st_size
                        with full_path.open("rb") as f_in:
                            tf.addfile(info, f_in)
    return _sha256_file(out_file)


def create_deterministic_zip(
    source_dir: str | Path,
    output_path: str | Path,
    *,
    arcname_prefix: str = "",
    exclude_fn: Callable[[str], bool] | None = is_excluded_release_path,
) -> str:
    """Create a reproducible `.zip` archive with fixed DOS timestamps, Unix modes, and member order."""
    src_root = Path(source_dir).resolve()
    out_file = Path(output_path).resolve()
    out_file.parent.mkdir(parents=True, exist_ok=True)
    prefix = arcname_prefix.strip("/")

    entries = _iter_deterministic_entries(src_root, exclude_fn=exclude_fn)
    with zipfile.ZipFile(
        out_file, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as zf:
        for rel_path, full_path in entries:
            arcname = f"{prefix}/{rel_path}" if prefix else rel_path
            if full_path.is_dir() and not full_path.is_symlink():
                zinfo = zipfile.ZipInfo(
                    filename=arcname.rstrip("/") + "/",
                    date_time=(1980, 1, 1, 0, 0, 0),
                )
                zinfo.create_system = 3
                zinfo.external_attr = (0o040755 << 16) | 0x10
                zf.writestr(zinfo, b"")
            elif full_path.is_file() and not full_path.is_symlink():
                zinfo = zipfile.ZipInfo(
                    filename=arcname,
                    date_time=(1980, 1, 1, 0, 0, 0),
                )
                zinfo.compress_type = zipfile.ZIP_DEFLATED
                zinfo.create_system = 3
                mode = 0o755 if os.access(full_path, os.X_OK) else 0o644
                zinfo.external_attr = (0o100000 | mode) << 16
                zf.writestr(
                    zinfo,
                    full_path.read_bytes(),
                    compress_type=zipfile.ZIP_DEFLATED,
                    compresslevel=9,
                )
    return _sha256_file(out_file)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalize_member_path(name: str, *, strip_prefix: str | None = None) -> str:
    norm = name.replace("\\", "/")
    while norm.startswith("./"):
        norm = norm[2:]
    norm = norm.lstrip("/")
    if strip_prefix:
        prefix = strip_prefix.strip("/") + "/"
        if norm.startswith(prefix):
            norm = norm[len(prefix) :]
        elif norm == strip_prefix.strip("/"):
            norm = ""
    return norm.strip("/")


def list_archive_members(archive_path: str | Path, *, strip_top_level: bool = False) -> list[str]:
    """Return normalized file/directory entries inside a `.tar.gz` or `.zip` archive."""
    path = Path(archive_path)
    if not path.is_file():
        raise FileNotFoundError(f"Archive does not exist: {path}")

    raw_names: list[str] = []
    if path.name.endswith((".tar.gz", ".tgz", ".tar")):
        with tarfile.open(path, "r:*") as tar:
            raw_names = [m.name for m in tar.getmembers()]
    elif path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path, "r") as zf:
            raw_names = zf.namelist()
    else:
        raise ValueError(f"Unsupported archive format: {path.name}")

    cleaned = []
    for n in raw_names:
        c = n.replace("\\", "/")
        while c.startswith("./"):
            c = c[2:]
        c = c.strip("/")
        if c and c != ".":
            cleaned.append(c)

    top_prefix: str | None = None
    if strip_top_level and cleaned:
        non_appledouble = [n for n in cleaned if not n.split("/")[-1].startswith("._")]
        first_parts = {n.split("/", 1)[0] for n in (non_appledouble or cleaned)}
        if len(first_parts) == 1:
            candidate = next(iter(first_parts))
            if any("/" in n for n in cleaned):
                top_prefix = candidate

    normalized = [
        _normalize_member_path(name, strip_prefix=top_prefix)
        for name in cleaned
    ]
    return sorted({n for n in normalized if n})


def audit_release_archive(
    archive_path: str | Path,
    *,
    required_paths: Sequence[str] = REQUIRED_ARCHIVE_PATHS,
    strip_top_level: bool = False,
) -> dict[str, Any]:
    """Audit a release or offline-bundle archive for required modules and forbidden leaks."""
    path = Path(archive_path).resolve()
    members = list_archive_members(path, strip_top_level=strip_top_level)
    member_set = set(members)

    missing_required = [req for req in required_paths if req not in member_set]
    forbidden_matches: list[dict[str, str]] = []

    for entry in members:
        entry_with_slash = entry + "/"
        for prefix in FORBIDDEN_ARCHIVE_PREFIXES:
            if entry.startswith(prefix.rstrip("/")) and (
                entry == prefix.rstrip("/") or entry.startswith(prefix)
            ):
                forbidden_matches.append({"path": entry, "reason": f"forbidden_prefix:{prefix}"})
                break
        else:
            parts = entry.split("/")
            if any(seg in FORBIDDEN_ARCHIVE_SEGMENTS for seg in parts):
                forbidden_matches.append({"path": entry, "reason": "forbidden_segment"})
                continue
            if any(entry.endswith(sfx) for sfx in FORBIDDEN_ARCHIVE_SUFFIXES):
                forbidden_matches.append({"path": entry, "reason": "forbidden_suffix"})
                continue
            base = parts[-1]
            if base == ".env" or (base.startswith(".env.") and base != ".env.example"):
                forbidden_matches.append({"path": entry, "reason": "forbidden_env_file"})

    passed = len(missing_required) == 0 and len(forbidden_matches) == 0
    return {
        "schema_version": SCHEMA_VERSION,
        "archive_path": str(path),
        "archive_sha256": _sha256_file(path),
        "archive_bytes": path.stat().st_size,
        "member_count": len(members),
        "passed": passed,
        "missing_required": missing_required,
        "forbidden_matches": forbidden_matches,
    }


def verify_workspace_integrity(
    region_root: str | Path,
    generation_root: str | Path | None = None,
) -> dict[str, Any]:
    """Verify SQLite schema, job manifests, `.npy` artifact SHA-256 digests, and generation run records."""
    r_root = Path(region_root).resolve()
    g_root = Path(generation_root).resolve() if generation_root is not None else None

    errors: list[str] = []
    job_summaries: list[dict[str, Any]] = []
    referenced_artifacts: set[str] = set()

    db_path = r_root / "jobs.sqlite3"
    user_version = 0
    if db_path.exists():
        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=10)
            try:
                user_version = int(conn.execute("PRAGMA user_version").fetchone()[0])
                if user_version not in (0, 1):
                    errors.append(f"Unsupported SQLite user_version: {user_version}")
                rows = conn.execute("SELECT id, manifest FROM jobs ORDER BY id ASC").fetchall()
            finally:
                conn.close()
        except Exception as exc:
            errors.append(f"SQLite read error: {exc}")
            rows = []

        for job_id, raw_manifest in rows:
            try:
                manifest = json.loads(raw_manifest)
            except Exception as exc:
                errors.append(f"Job {job_id}: invalid JSON manifest ({exc})")
                continue

            if manifest.get("id") != job_id:
                errors.append(f"Job {job_id}: manifest id mismatch ({manifest.get('id')!r})")
            if manifest.get("schema_version") != 1:
                errors.append(
                    f"Job {job_id}: unsupported manifest schema_version {manifest.get('schema_version')!r}"
                )

            artifacts = manifest.get("artifacts", {})
            if not isinstance(artifacts, Mapping) or "base" not in artifacts or "master" not in artifacts:
                errors.append(f"Job {job_id}: missing required base/master artifacts")
                continue

            artifact_digests: dict[str, str] = {}
            for name, desc in sorted(artifacts.items()):
                rel_path = desc.get("path", "")
                referenced_artifacts.add(rel_path)
                art_path = (r_root / rel_path).resolve()
                if not art_path.is_relative_to(r_root / "artifacts") or art_path.suffix != ".npy":
                    errors.append(f"Job {job_id} artifact {name}: invalid path {rel_path!r}")
                    continue
                if not art_path.is_file():
                    errors.append(f"Job {job_id} artifact {name}: missing file {rel_path!r}")
                    continue
                actual_bytes = art_path.stat().st_size
                expected_bytes = int(desc.get("bytes", -1))
                if actual_bytes != expected_bytes:
                    errors.append(
                        f"Job {job_id} artifact {name}: byte size mismatch ({actual_bytes} != {expected_bytes})"
                    )
                actual_sha = _sha256_file(art_path)
                expected_sha = str(desc.get("sha256", ""))
                if actual_sha != expected_sha:
                    errors.append(
                        f"Job {job_id} artifact {name}: sha256 mismatch ({actual_sha} != {expected_sha})"
                    )
                artifact_digests[name] = actual_sha

            job_summaries.append(
                {
                    "id": job_id,
                    "revision": int(manifest.get("revision", 0)),
                    "label": str(manifest.get("label", "")),
                    "profile": str(manifest.get("profile", "")),
                    "dimensions": list(manifest.get("dimensions", [])),
                    "artifact_count": len(artifact_digests),
                    "artifact_sha256": artifact_digests,
                }
            )

    artifacts_dir = r_root / "artifacts"
    unreferenced_files: list[str] = []
    if artifacts_dir.is_dir():
        for npy_file in sorted(artifacts_dir.glob("*.npy")):
            rel = str(npy_file.relative_to(r_root))
            if rel not in referenced_artifacts:
                unreferenced_files.append(rel)

    generation_runs: list[dict[str, Any]] = []
    generation_tasks: list[dict[str, Any]] = []
    if g_root is not None and g_root.exists():
        runs_dir = g_root / "runs"
        if runs_dir.is_dir():
            for run_file in sorted(runs_dir.glob("*.json")):
                try:
                    payload = json.loads(run_file.read_text(encoding="utf-8"))
                except Exception as exc:
                    errors.append(f"Generation run {run_file.name}: invalid JSON ({exc})")
                    continue
                run_id = str(payload.get("id", ""))
                if not run_id or f"{run_id}.json" != run_file.name:
                    errors.append(
                        f"Generation run {run_file.name}: id mismatch ({run_id!r})"
                    )
                if payload.get("schema_version") != 1:
                    errors.append(
                        f"Generation run {run_file.name}: unsupported schema_version {payload.get('schema_version')!r}"
                    )
                generation_runs.append(
                    {
                        "id": run_id,
                        "job_id": payload.get("job_id"),
                        "base_revision": payload.get("base_revision"),
                        "status": payload.get("status"),
                        "sha256": _sha256_file(run_file),
                    }
                )

        for rel_db in ("generation.sqlite3", "runs/generation.sqlite3"):
            gen_db = g_root / rel_db
            if not gen_db.is_file():
                continue
            try:
                conn = sqlite3.connect(f"file:{gen_db}?mode=ro", uri=True, timeout=5)
                try:
                    integ = conn.execute("PRAGMA integrity_check;").fetchone()
                    if not integ or integ[0] != "ok":
                        errors.append(f"SQLite integrity_check failed on {rel_db}: {integ}")
                    has_runs = conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name='runs'"
                    ).fetchone()
                    rows = (
                        conn.execute("SELECT run_id, record FROM runs ORDER BY run_id").fetchall()
                        if has_runs
                        else []
                    )
                finally:
                    conn.close()
            except sqlite3.Error as exc:
                errors.append(f"SQLite error reading {rel_db}: {exc}")
                rows = []

            for db_run_id, raw_record in rows:
                try:
                    payload = json.loads(raw_record)
                except Exception as exc:
                    errors.append(f"Generation ledger {rel_db} run {db_run_id}: invalid JSON ({exc})")
                    continue
                rec_id = str(payload.get("id", ""))
                if rec_id != db_run_id:
                    errors.append(
                        f"Generation ledger {rel_db} run {db_run_id}: id mismatch ({rec_id!r})"
                    )
                expected_out_sha = payload.get("output_sha256")
                cache_png = gen_db.parent / f"{db_run_id}.png"
                if payload.get("status") == "completed" or expected_out_sha:
                    if not cache_png.is_file():
                        errors.append(
                            f"Generation ledger {rel_db} run {db_run_id}: missing cached output {cache_png.name}"
                        )
                    elif expected_out_sha and _sha256_file(cache_png) != expected_out_sha:
                        errors.append(
                            f"Generation ledger {rel_db} run {db_run_id}: cached output sha256 mismatch"
                        )
                generation_runs.append(
                    {
                        "id": db_run_id,
                        "ledger": rel_db,
                        "status": payload.get("status"),
                        "prompt_id": payload.get("prompt_id"),
                        "workflow_hash": payload.get("workflow_hash"),
                        "output_sha256": expected_out_sha,
                        "record_sha256": hashlib.sha256(
                            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(
                                "utf-8"
                            )
                        ).hexdigest(),
                    }
                )

        queue_db = g_root / "queue.sqlite3"
        if queue_db.is_file():
            try:
                conn = sqlite3.connect(f"file:{queue_db}?mode=ro", uri=True, timeout=5)
                try:
                    integ = conn.execute("PRAGMA integrity_check;").fetchone()
                    if not integ or integ[0] != "ok":
                        errors.append(f"SQLite integrity_check failed on queue.sqlite3: {integ}")
                    has_tasks = conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name='tasks'"
                    ).fetchone()
                    q_rows = (
                        conn.execute(
                            "SELECT idx, task_id, record FROM tasks ORDER BY idx, task_id"
                        ).fetchall()
                        if has_tasks
                        else []
                    )
                finally:
                    conn.close()
            except sqlite3.Error as exc:
                errors.append(f"SQLite error reading queue.sqlite3: {exc}")
                q_rows = []

            for _idx, db_task_id, raw_record in q_rows:
                try:
                    payload = json.loads(raw_record)
                except Exception as exc:
                    errors.append(f"Generation queue task {db_task_id}: invalid JSON ({exc})")
                    continue
                rec_id = str(payload.get("id", ""))
                if rec_id != db_task_id:
                    errors.append(
                        f"Generation queue task {db_task_id}: id mismatch ({rec_id!r})"
                    )
                generation_tasks.append(
                    {
                        "id": db_task_id,
                        "job_id": payload.get("job_id"),
                        "base_revision": payload.get("base_revision"),
                        "run_id": payload.get("run_id"),
                        "status": payload.get("status"),
                        "output_sha256": payload.get("output_sha256"),
                        "record_sha256": hashlib.sha256(
                            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(
                                "utf-8"
                            )
                        ).hexdigest(),
                    }
                )

    state_fingerprint = hashlib.sha256(
        json.dumps(
            {
                "user_version": user_version,
                "jobs": job_summaries,
                "generation_runs": generation_runs,
                "generation_tasks": generation_tasks,
            },
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()

    return {
        "schema_version": SCHEMA_VERSION,
        "region_root": str(r_root),
        "generation_root": str(g_root) if g_root is not None else None,
        "passed": len(errors) == 0,
        "sqlite_user_version": user_version,
        "job_count": len(job_summaries),
        "referenced_artifact_count": len(referenced_artifacts),
        "unreferenced_artifact_count": len(unreferenced_files),
        "unreferenced_artifacts": unreferenced_files,
        "generation_run_count": len(generation_runs),
        "generation_task_count": len(generation_tasks),
        "state_fingerprint": state_fingerprint,
        "jobs": job_summaries,
        "generation_runs": generation_runs,
        "generation_tasks": generation_tasks,
        "errors": errors,
    }


def _backup_sqlite_file(src_db: Path, dst_db: Path) -> None:
    dst_db.parent.mkdir(parents=True, exist_ok=True)
    src_conn = sqlite3.connect(f"file:{src_db}?mode=ro", uri=True, timeout=30)
    try:
        dst_conn = sqlite3.connect(dst_db, timeout=30)
        try:
            src_conn.backup(dst_conn)
        finally:
            dst_conn.close()
    finally:
        src_conn.close()


def create_workspace_snapshot(
    region_root: str | Path,
    snapshot_dir: str | Path,
    *,
    generation_root: str | Path | None = None,
    target_version: str = "unknown",
) -> dict[str, Any]:
    """Create a verified, consistent pre-upgrade snapshot of `region_jobs` and `generation_runs`."""
    r_root = Path(region_root).resolve()
    g_root = Path(generation_root).resolve() if generation_root is not None else None
    snap_root = Path(snapshot_dir).resolve()

    pre_check = verify_workspace_integrity(r_root, g_root)
    if not pre_check["passed"]:
        raise ValueError(
            f"Refusing to snapshot corrupted workspace: {'; '.join(pre_check['errors'])}"
        )

    snap_root.mkdir(parents=True, exist_ok=True)
    snap_region = snap_root / "region_jobs"
    snap_gen = snap_root / "generation_runs"
    if snap_region.exists():
        shutil.rmtree(snap_region)
    if snap_gen.exists():
        shutil.rmtree(snap_gen)

    snap_region.mkdir(parents=True, exist_ok=True)
    (snap_region / "artifacts").mkdir(parents=True, exist_ok=True)

    db_src = r_root / "jobs.sqlite3"
    if db_src.is_file():
        _backup_sqlite_file(db_src, snap_region / "jobs.sqlite3")

    artifacts_src = r_root / "artifacts"
    if artifacts_src.is_dir():
        for npy_file in sorted(artifacts_src.glob("*.npy")):
            shutil.copy2(npy_file, snap_region / "artifacts" / npy_file.name)

    if g_root is not None and g_root.exists():
        snap_gen.mkdir(parents=True, exist_ok=True)
        for rel_db in ("generation.sqlite3", "queue.sqlite3", "runs/generation.sqlite3"):
            src_db = g_root / rel_db
            if src_db.is_file():
                _backup_sqlite_file(src_db, snap_gen / rel_db)
        for png_file in sorted(g_root.glob("*.png")):
            shutil.copy2(png_file, snap_gen / png_file.name)
        runs_src = g_root / "runs"
        if runs_src.is_dir():
            snap_runs_dst = snap_gen / "runs"
            snap_runs_dst.mkdir(parents=True, exist_ok=True)
            for run_file in sorted(runs_src.glob("*.json")):
                shutil.copy2(run_file, snap_runs_dst / run_file.name)
            for png_file in sorted(runs_src.glob("*.png")):
                shutil.copy2(png_file, snap_runs_dst / png_file.name)

    snap_check = verify_workspace_integrity(
        snap_region, snap_gen if (g_root is not None) else None
    )
    if not snap_check["passed"] or snap_check["state_fingerprint"] != pre_check["state_fingerprint"]:
        raise RuntimeError("Snapshot verification failed after copy")

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "target_version": str(target_version),
        "source_region_root": str(r_root),
        "source_generation_root": str(g_root) if g_root is not None else None,
        "snapshot_dir": str(snap_root),
        "integrity": snap_check,
    }
    manifest_path = snap_root / "snapshot-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def restore_workspace_snapshot(
    snapshot_dir: str | Path,
    region_root: str | Path,
    *,
    generation_root: str | Path | None = None,
) -> dict[str, Any]:
    """Atomically restore `region_jobs` and `generation_runs` from a verified snapshot."""
    snap_root = Path(snapshot_dir).resolve()
    manifest_path = snap_root / "snapshot-manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Snapshot manifest missing: {manifest_path}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"Unsupported snapshot schema: {manifest.get('schema_version')!r}")

    snap_region = snap_root / "region_jobs"
    snap_gen = snap_root / "generation_runs"
    expected_fp = manifest["integrity"]["state_fingerprint"]

    snap_verify = verify_workspace_integrity(
        snap_region, snap_gen if snap_gen.exists() else None
    )
    if not snap_verify["passed"] or snap_verify["state_fingerprint"] != expected_fp:
        raise ValueError("Snapshot directory failed pre-restore integrity verification")

    r_root = Path(region_root).resolve()
    g_root = Path(generation_root).resolve() if generation_root is not None else None

    _atomic_replace_tree(snap_region, r_root)
    if g_root is not None and snap_gen.exists():
        _atomic_replace_tree(snap_gen, g_root)

    restored_verify = verify_workspace_integrity(r_root, g_root)
    if not restored_verify["passed"] or restored_verify["state_fingerprint"] != expected_fp:
        raise RuntimeError("Restored workspace failed post-restore integrity verification")

    return {
        "schema_version": SCHEMA_VERSION,
        "restored_at": datetime.now(timezone.utc).isoformat(),
        "snapshot_dir": str(snap_root),
        "region_root": str(r_root),
        "generation_root": str(g_root) if g_root is not None else None,
        "state_fingerprint": restored_verify["state_fingerprint"],
        "integrity": restored_verify,
    }


def _atomic_replace_tree(source_dir: Path, target_dir: Path) -> None:
    parent = target_dir.parent
    parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{target_dir.name}-stage-", dir=str(parent)))
    backup = parent / f".{target_dir.name}-rollback-{uuid.uuid4().hex[:8]}"
    try:
        shutil.rmtree(staging)
        shutil.copytree(source_dir, staging)
        if target_dir.exists():
            os.replace(target_dir, backup)
        os.replace(staging, target_dir)
        if backup.exists():
            shutil.rmtree(backup)
    except BaseException:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        if not target_dir.exists() and backup.exists():
            os.replace(backup, target_dir)
        raise
