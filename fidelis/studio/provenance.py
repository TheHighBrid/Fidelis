"""Candidate model provenance, weight-hash verification, and usage-terms audit (F05-B / MEL-75)."""

from __future__ import annotations

import csv
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any, Dict, List, Optional

SCHEMA_VERSION = 1
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

VALID_PROVENANCE_STATUS = ("pinned_sha256", "unpinned_upstream", "not_acquired")
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


def sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def load_tsv_candidates(tsv_path: Path) -> Dict[str, Dict[str, str]]:
    """Parse config/photo-candidates.tsv keyed by candidate name."""
    records: Dict[str, Dict[str, str]] = {}
    with tsv_path.open("r", encoding="utf-8") as stream:
        rows = csv.reader((line for line in stream if not line.startswith("#")), delimiter="\t")
        for row in rows:
            if not row:
                continue
            if len(row) < 7:
                raise ProvenanceError(f"Malformed TSV row in {tsv_path.name}: {row!r}")
            name, role, revision, folder, param_sha, bin_sha, license_note = row[:7]
            records[name] = {
                "role": role,
                "revision": revision,
                "folder": folder,
                "param_sha256": param_sha,
                "bin_sha256": bin_sha,
                "license_note": license_note,
            }
    return records


def validate_provenance_catalog(
    catalog: Any,
    *,
    tsv_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Validate provenance schema, pinned-hash requirements, terms gates, and TSV parity."""
    if not isinstance(catalog, dict):
        raise ProvenanceError("Provenance catalog must be a JSON object")
    if catalog.get("schema_version") != SCHEMA_VERSION:
        raise ProvenanceError(f"Unsupported provenance schema_version: {catalog.get('schema_version')!r}")

    runtimes = catalog.get("runtimes")
    models = catalog.get("models")
    if not isinstance(runtimes, list) or not isinstance(models, list) or not models:
        raise ProvenanceError("Provenance catalog requires non-empty 'models' list and 'runtimes' list")

    tsv_map = load_tsv_candidates(tsv_path) if tsv_path is not None else None
    seen_ids = set()
    by_provenance: Dict[str, int] = {k: 0 for k in VALID_PROVENANCE_STATUS}
    by_commercial: Dict[str, int] = {}

    for entry in models:
        if not isinstance(entry, dict):
            raise ProvenanceError("Each model entry must be an object")
        mid = entry.get("model_id")
        if not isinstance(mid, str) or not mid.strip() or mid in seen_ids:
            raise ProvenanceError(f"Missing or duplicate model_id: {mid!r}")
        seen_ids.add(mid)

        prov_status = entry.get("provenance_status")
        if prov_status not in VALID_PROVENANCE_STATUS:
            raise ProvenanceError(f"{mid}: invalid provenance_status {prov_status!r}")
        by_provenance[prov_status] += 1

        source = entry.get("source")
        weights = entry.get("weights")
        terms = entry.get("terms")
        if not isinstance(source, dict) or not isinstance(weights, dict) or not isinstance(terms, dict):
            raise ProvenanceError(f"{mid}: source, weights, and terms must be objects")

        comm_status = terms.get("commercial_status")
        if comm_status not in VALID_COMMERCIAL_STATUS:
            raise ProvenanceError(f"{mid}: invalid terms.commercial_status {comm_status!r}")
        by_commercial[comm_status] = by_commercial.get(comm_status, 0) + 1

        cleared = terms.get("production_terms_cleared")
        if not isinstance(cleared, bool):
            raise ProvenanceError(f"{mid}: terms.production_terms_cleared must be boolean")

        if entry.get("quality_certified") is not False:
            raise ProvenanceError(
                f"{mid}: quality_certified must remain false until held-out F05/F13 acceptance passes"
            )

        if prov_status == "pinned_sha256":
            rev = source.get("revision")
            if not isinstance(rev, str) or not rev.strip():
                raise ProvenanceError(f"{mid}: pinned_sha256 requires source.revision")
            if not weights:
                raise ProvenanceError(f"{mid}: pinned_sha256 requires non-empty weights hash mapping")
            for fname, sha in weights.items():
                if not isinstance(sha, str) or not _SHA256_RE.fullmatch(sha):
                    raise ProvenanceError(f"{mid}: invalid SHA-256 hash for weight file {fname!r}")
        else:
            for fname, sha in weights.items():
                if sha is not None and (not isinstance(sha, str) or not _SHA256_RE.fullmatch(sha)):
                    raise ProvenanceError(f"{mid}: malformed weight hash for {fname!r}")

        # Production terms clearance requires BOTH permissive terms AND pinned byte hashes
        if cleared and (comm_status != "cleared_permissive" or prov_status != "pinned_sha256"):
            raise ProvenanceError(
                f"{mid}: production_terms_cleared=true requires commercial_status=cleared_permissive and provenance_status=pinned_sha256"
            )

        if tsv_map is not None and mid in tsv_map:
            tsv = tsv_map[mid]
            if prov_status != "pinned_sha256":
                raise ProvenanceError(f"{mid}: cataloged TSV candidate must keep provenance_status=pinned_sha256")
            if source.get("revision") != tsv["revision"] or source.get("folder") != tsv["folder"]:
                raise ProvenanceError(f"{mid}: source revision/folder differs from config/photo-candidates.tsv")
            if weights.get("x4.param") != tsv["param_sha256"] or weights.get("x4.bin") != tsv["bin_sha256"]:
                raise ProvenanceError(f"{mid}: weight hashes differ from config/photo-candidates.tsv")

    if tsv_map is not None:
        missing_from_json = set(tsv_map) - seen_ids
        if missing_from_json:
            raise ProvenanceError(
                f"Candidates in photo-candidates.tsv missing from model-provenance-v1.json: {sorted(missing_from_json)}"
            )

    return {
        "schema_version": SCHEMA_VERSION,
        "model_count": len(models),
        "runtime_count": len(runtimes),
        "by_provenance_status": by_provenance,
        "by_commercial_status": by_commercial,
        "tsv_cross_checked": tsv_map is not None,
    }


def audit_model_provenance(
    repo_root: Path,
    app_home: Optional[Path] = None,
) -> Dict[str, Any]:
    """Validate provenance catalog and compare declared weights against local FIDELIS_HOME."""
    repo = Path(repo_root).resolve()
    home = Path(app_home or os.environ.get("FIDELIS_HOME", str(Path.home() / ".local" / "share" / "fidelis")))
    catalog_path = repo / "config" / "model-provenance-v1.json"
    tsv_path = repo / "config" / "photo-candidates.tsv"

    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    summary = validate_provenance_catalog(catalog, tsv_path=tsv_path)

    model_reports: List[Dict[str, Any]] = []
    for entry in catalog["models"]:
        rel_dir = entry.get("local_relative_dir")
        weights = entry.get("weights", {})
        file_checks: Dict[str, Dict[str, Any]] = {}
        installed = False
        integrity = "not_applicable"

        if rel_dir and weights:
            target_dir = home / rel_dir
            all_present = True
            any_present = False
            any_mismatch = False
            all_matched = True

            for fname, expected_sha in weights.items():
                fp = target_dir / fname
                exists = fp.is_file()
                if exists:
                    any_present = True
                    actual_sha = sha256_file(fp)
                    size_bytes = fp.stat().st_size
                    if expected_sha is None:
                        all_matched = False
                        status = "unpinned_local"
                    elif actual_sha == expected_sha:
                        status = "matched"
                    else:
                        all_matched = False
                        any_mismatch = True
                        status = "mismatch"
                    file_checks[fname] = {
                        "present": True,
                        "bytes": size_bytes,
                        "actual_sha256": actual_sha,
                        "expected_sha256": expected_sha,
                        "status": status,
                    }
                else:
                    all_present = False
                    all_matched = False
                    file_checks[fname] = {
                        "present": False,
                        "expected_sha256": expected_sha,
                        "status": "missing",
                    }

            installed = all_present
            if not any_present:
                integrity = "missing"
            elif any_mismatch:
                integrity = "mismatch"
            elif all_present and all_matched:
                integrity = "matched"
            elif all_present:
                integrity = "unpinned_local"
            else:
                integrity = "incomplete"
        else:
            integrity = "not_acquired" if entry["provenance_status"] == "not_acquired" else "missing"

        model_reports.append(
            {
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
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "catalog_summary": summary,
        "app_home": str(home),
        "models": model_reports,
    }
