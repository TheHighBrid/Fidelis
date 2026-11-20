"""Candidate model provenance, weight-hash verification, and usage-terms audit (F05-B / MEL-75)."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
from pathlib import Path, PureWindowsPath
from typing import Any

SCHEMA_VERSION = 1
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

VALID_PROVENANCE_STATUS = ("pinned_sha256", "unpinned_upstream", "not_acquired")
VALID_RUNTIME_PROVENANCE_STATUS = (
    "pinned_sha256",
    "tagged_release_archive_unhashed",
    "unpinned_upstream",
)
VALID_COMMERCIAL_STATUS = (
    "cleared_permissive",
    "cleared_permissive_unpinned_bytes",
    "non_commercial_restricted",
    "copyleft_agpl_restricted",
    "evaluation_only_unverified",
    "unclear_terms_review_required",
    "unverified_terms",
    "rejected_quality",
)


class ProvenanceError(ValueError):
    """Raised when model provenance catalog contracts or checksum invariants fail."""


def _validate_relative_path(value, *, field, single_name=False):
    """Require canonical portable relative paths before inspecting local bytes."""
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise ProvenanceError(f"Invalid relative path in {field}")
    parts = value.split("/")
    if (any(part in ("", ".", "..") for part in parts)
            or PureWindowsPath(value).drive or any(":" in part for part in parts)
            or (single_name and len(parts) != 1)):
        raise ProvenanceError(f"Invalid relative path in {field}")


def confined_local_path(home, relative):
    candidate = home / relative
    try:
        resolved = candidate.resolve()
        resolved.relative_to(home.resolve())
    except (ValueError, OSError, RuntimeError) as error:
        raise ProvenanceError("Local provenance path escapes the configured app home") from error
    return resolved


def sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def load_tsv_candidates(tsv_path: Path) -> dict[str, dict[str, str]]:
    """Parse config/photo-candidates.tsv keyed by candidate name."""
    records: dict[str, dict[str, str]] = {}
    with tsv_path.open("r", encoding="utf-8") as stream:
        rows = csv.reader((line for line in stream if not line.startswith("#")), delimiter="\t")
        for row in rows:
            if not row:
                continue
            if len(row) < 7:
                raise ProvenanceError(f"Malformed TSV row in {tsv_path.name}: {row!r}")
            name, role, revision, folder, param_sha, bin_sha, license_note = row[:7]
            if not name.strip() or name in records:
                raise ProvenanceError("Missing or duplicate TSV candidate name")
            _validate_relative_path(folder, field="TSV candidate folder", single_name=True)
            records[name] = {
                "role": role,
                "revision": revision,
                "folder": folder,
                "param_sha256": param_sha,
                "bin_sha256": bin_sha,
                "license_note": license_note,
            }
    return records


def _validate_runtimes(runtimes):
    seen_runtime_ids = set()
    for rt in runtimes:
        if not isinstance(rt, dict):
            raise ProvenanceError("Each runtime entry must be an object")
        rid = rt.get("runtime_id")
        if not isinstance(rid, str) or not rid.strip() or rid in seen_runtime_ids:
            raise ProvenanceError(f"Missing or duplicate runtime_id: {rid!r}")
        seen_runtime_ids.add(rid)
        _validate_runtime_fields(rid, rt)


def _validate_runtime_fields(rid, rt):
    if rt.get("provenance_status") not in VALID_RUNTIME_PROVENANCE_STATUS:
        raise ProvenanceError(f"{rid}: invalid runtime provenance_status {rt.get('provenance_status')!r}")
    if rt.get("commercial_status") not in VALID_COMMERCIAL_STATUS:
        raise ProvenanceError(f"{rid}: invalid runtime commercial_status {rt.get('commercial_status')!r}")
    if not isinstance(rt.get("revision"), str) or not rt.get("revision").strip():
        raise ProvenanceError(f"{rid}: runtime requires non-empty revision")
    for sha_field in ("archive_sha256", "macos_binary_sha256"):
        sha_val = rt.get(sha_field)
        if sha_val is not None and (not isinstance(sha_val, str) or not _SHA256_RE.fullmatch(sha_val)):
            raise ProvenanceError(f"{rid}: malformed {sha_field} {sha_val!r}")
    if rt.get("local_relative_path") is not None:
        _validate_relative_path(rt["local_relative_path"], field=f"{rid}: runtime path")
    if rt["provenance_status"] == "pinned_sha256" and rt.get("archive_sha256") is None:
        raise ProvenanceError(f"{rid}: pinned runtime requires an archive SHA-256")

def _validate_model_identity(entry, seen_ids):
    if not isinstance(entry, dict):
        raise ProvenanceError("Each model entry must be an object")
    mid = entry.get("model_id")
    if not isinstance(mid, str) or not mid.strip() or mid in seen_ids:
        raise ProvenanceError(f"Missing or duplicate model_id: {mid!r}")
    seen_ids.add(mid)
    prov_status = entry.get("provenance_status")
    if prov_status not in VALID_PROVENANCE_STATUS:
        raise ProvenanceError(f"{mid}: invalid provenance_status {prov_status!r}")
    for field in ("source", "weights", "terms"):
        if not isinstance(entry.get(field), dict):
            raise ProvenanceError(f"{mid}: source, weights, and terms must be objects")
    return mid, prov_status


def _validate_model_terms(mid, entry, prov_status):
    terms = entry["terms"]
    comm_status = terms.get("commercial_status")
    if comm_status not in VALID_COMMERCIAL_STATUS:
        raise ProvenanceError(f"{mid}: invalid terms.commercial_status {comm_status!r}")
    cleared = terms.get("production_terms_cleared")
    if not isinstance(cleared, bool):
        raise ProvenanceError(f"{mid}: terms.production_terms_cleared must be boolean")
    if entry.get("quality_certified") is not False:
        raise ProvenanceError(f"{mid}: quality_certified must remain false until held-out F05/F13 acceptance passes")
    if cleared and (comm_status != "cleared_permissive" or prov_status != "pinned_sha256"):
        raise ProvenanceError(f"{mid}: production_terms_cleared=true requires commercial_status=cleared_permissive and provenance_status=pinned_sha256")
    return comm_status


def _validate_weight_hashes(mid, source, weights, prov_status):
    pinned = prov_status == "pinned_sha256"
    if pinned:
        rev = source.get("revision")
        if not isinstance(rev, str) or not rev.strip():
            raise ProvenanceError(f"{mid}: pinned_sha256 requires source.revision")
        if not weights:
            raise ProvenanceError(f"{mid}: pinned_sha256 requires non-empty weights hash mapping")
    for fname, sha in weights.items():
        _validate_relative_path(fname, field=f"{mid}: weight filename", single_name=True)
        if sha is None and not pinned:
            continue
        if not isinstance(sha, str) or not _SHA256_RE.fullmatch(sha):
            if pinned:
                raise ProvenanceError(f"{mid}: invalid SHA-256 hash for weight file {fname!r}")
            raise ProvenanceError(f"{mid}: malformed weight hash for {fname!r}")


def _cross_check_candidate(mid, source, weights, prov_status, tsv):
    if prov_status != "pinned_sha256":
        raise ProvenanceError(f"{mid}: cataloged TSV candidate must keep provenance_status=pinned_sha256")
    if source.get("revision") != tsv["revision"] or source.get("folder") != tsv["folder"]:
        raise ProvenanceError(f"{mid}: source revision/folder differs from config/photo-candidates.tsv")
    if weights.get("x4.param") != tsv["param_sha256"] or weights.get("x4.bin") != tsv["bin_sha256"]:
        raise ProvenanceError(f"{mid}: weight hashes differ from config/photo-candidates.tsv")


def _validate_models(models, tsv_map):
    seen_ids = set()
    by_provenance = dict.fromkeys(VALID_PROVENANCE_STATUS, 0)
    by_commercial = {}
    for entry in models:
        mid, prov_status = _validate_model_identity(entry, seen_ids)
        source, weights = entry["source"], entry["weights"]
        if entry.get("local_relative_dir") is not None:
            _validate_relative_path(entry["local_relative_dir"], field=f"{mid}: model directory")
        comm_status = _validate_model_terms(mid, entry, prov_status)
        _validate_weight_hashes(mid, source, weights, prov_status)
        by_provenance[prov_status] += 1
        by_commercial[comm_status] = by_commercial.get(comm_status, 0) + 1
        if tsv_map is not None and mid in tsv_map:
            _cross_check_candidate(mid, source, weights, prov_status, tsv_map[mid])

    if tsv_map is not None:
        missing_from_json = set(tsv_map) - seen_ids
        if missing_from_json:
            raise ProvenanceError(
                f"Candidates in photo-candidates.tsv missing from model-provenance-v1.json: {sorted(missing_from_json)}"
            )
    return by_provenance, by_commercial


def validate_provenance_catalog(
    catalog: Any,
    *,
    tsv_path: Path | None = None,
) -> dict[str, Any]:
    """Validate provenance schema, pinned-hash requirements, terms gates, and TSV parity."""
    if not isinstance(catalog, dict):
        raise ProvenanceError("Provenance catalog must be a JSON object")
    if catalog.get("schema_version") != SCHEMA_VERSION:
        raise ProvenanceError(f"Unsupported provenance schema_version: {catalog.get('schema_version')!r}")
    runtimes, models = catalog.get("runtimes"), catalog.get("models")
    if not isinstance(runtimes, list) or not runtimes or not isinstance(models, list) or not models:
        raise ProvenanceError("Provenance catalog requires non-empty 'models' list and 'runtimes' list")
    _validate_runtimes(runtimes)
    tsv_map = load_tsv_candidates(tsv_path) if tsv_path is not None else None
    by_provenance, by_commercial = _validate_models(models, tsv_map)

    return {
        "schema_version": SCHEMA_VERSION,
        "model_count": len(models),
        "runtime_count": len(runtimes),
        "by_provenance_status": by_provenance,
        "by_commercial_status": by_commercial,
        "tsv_cross_checked": tsv_map is not None,
    }


def _inspect_file(path, expected_sha):
    if path is None or not path.is_file():
        return {"present": False, "expected_sha256": expected_sha, "status": "missing"}
    actual_sha = sha256_file(path)
    status = "unpinned_local" if expected_sha is None else ("matched" if actual_sha == expected_sha else "mismatch")
    return {
        "present": True,
        "bytes": path.stat().st_size,
        "actual_sha256": actual_sha,
        "expected_sha256": expected_sha,
        "status": status,
    }


def _audit_runtime(rt, home):
    relative = rt.get("local_relative_path")
    path = confined_local_path(home, relative) if relative is not None else None
    checked = _inspect_file(path, rt.get("macos_binary_sha256"))
    return {
        "runtime_id": rt["runtime_id"],
        "role": rt["role"],
        "revision": rt["revision"],
        "provenance_status": rt["provenance_status"],
        "installed": checked["present"],
        "integrity": checked["status"],
        "actual_sha256": checked.get("actual_sha256"),
        "expected_binary_sha256": checked["expected_sha256"],
        "bytes": checked.get("bytes"),
        "license": rt["license"],
        "commercial_status": rt["commercial_status"],
    }


def _weight_integrity(checks):
    statuses = {item["status"] for item in checks.values()}
    installed = "missing" not in statuses
    if statuses == {"missing"}:
        return installed, "missing"
    if "mismatch" in statuses:
        return installed, "mismatch"
    if statuses == {"matched"}:
        return installed, "matched"
    return installed, "unpinned_local" if installed else "incomplete"


def _audit_model(entry, home):
    rel_dir, weights = entry.get("local_relative_dir"), entry.get("weights", {})
    file_checks = {}
    installed = False
    integrity = "not_acquired" if entry["provenance_status"] == "not_acquired" else "missing"
    if rel_dir and weights:
        confined_local_path(home, rel_dir)
        file_checks = {
            name: _inspect_file(confined_local_path(home, f"{rel_dir}/{name}"), sha)
            for name, sha in weights.items()
        }
        installed, integrity = _weight_integrity(file_checks)
    return {
        "model_id": entry["model_id"],
        "lane": entry["lane"],
        "role": entry["role"],
        "provenance_status": entry["provenance_status"],
        "installed": installed,
        "integrity": integrity,
        "license": entry["terms"]["license"],
        "commercial_status": entry["terms"]["commercial_status"],
        "production_terms_cleared": entry["terms"]["production_terms_cleared"],
        "quality_certified": entry["quality_certified"],
        "files": file_checks,
    }


def audit_model_provenance(
    repo_root: Path,
    app_home: Path | None = None,
) -> dict[str, Any]:
    """Validate provenance catalog and compare declared weights against local FIDELIS_HOME."""
    repo = Path(repo_root).resolve()
    home = Path(app_home or os.environ.get("FIDELIS_HOME", str(Path.home() / ".local" / "share" / "fidelis")))
    catalog_path = repo / "config" / "model-provenance-v1.json"
    tsv_path = repo / "config" / "photo-candidates.tsv"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    summary = validate_provenance_catalog(catalog, tsv_path=tsv_path)

    return {
        "schema_version": SCHEMA_VERSION,
        "catalog_summary": summary,
        "app_home": str(home),
        "runtimes": [_audit_runtime(runtime, home) for runtime in catalog["runtimes"]],
        "models": [_audit_model(model, home) for model in catalog["models"]],
    }
