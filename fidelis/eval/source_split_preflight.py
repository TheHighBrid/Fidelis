"""Read-only source-SHA split checks; no image IO or acceptance decisions.

Only explicitly supplied JSON manifests are read. Missing hashes remain unknown;
this check cannot certify source bytes, derivatives, capture groups or run history.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path


def _records(document):
    if not isinstance(document, dict) or document.get("schema_version") != 1:
        raise ValueError("Expected a schema_version 1 manifest object")
    collections = [key for key in ("cases", "assets") if key in document]
    if len(collections) != 1 or not isinstance(document[collections[0]], list):
        raise ValueError("Expected exactly one cases or assets array")
    key = collections[0]
    return key, document[key]


def _alias(record, collection, manifest, index):
    if not isinstance(record, dict):
        raise ValueError("Record must be an object")
    identity_key = "asset_id" if collection == "assets" else "case_id"
    identity = record.get(identity_key)
    if identity is None and collection == "cases":
        identity = record.get("id")
    if not isinstance(identity, str) or not identity.strip():
        raise ValueError("Record needs a nonempty case_id, asset_id or diagnostic id")
    split = record.get("split")
    if split not in ("calibration", "held_out"):
        raise ValueError("Record split must be calibration or held_out")
    source = record.get("source", {})
    if not isinstance(source, dict):
        raise ValueError("Record source must be an object")
    # Production inventories use source.sha256; explicit diagnostic manifests use
    # source_sha256. Reject disagreement instead of silently choosing a value.
    nested = source.get("sha256")
    diagnostic = record.get("source_sha256")
    hashes = []
    for value in (nested, diagnostic):
        if value is None or value == "":
            continue
        if not isinstance(value, str) or re.fullmatch(r"[0-9a-fA-F]{64}", value) is None:
            raise ValueError("Nonempty source SHA-256 must contain exactly 64 hex characters")
        hashes.append(value.lower())
    if len(set(hashes)) > 1:
        raise ValueError("source.sha256 and source_sha256 disagree")
    return {
        "manifest": manifest,
        "collection": collection,
        "record_index": index,
        "id": identity,
        "split": split,
        "sha256": hashes[0] if hashes else None,
    }


def check_source_split_isolation(manifest_paths):
    """Return JSON-compatible evidence; conflicts/invalid/unknown inputs cannot pass.

    Null/empty hashes are listed individually as unknown, never joined together.
    A passing result only covers declared nonempty SHA identities in these inputs.
    It does not establish release readiness or an untouched held-out history.
    """
    manifests = []
    errors = []
    aliases_by_hash = defaultdict(list)
    unknown = []
    paths = list(manifest_paths)
    if not paths:
        errors.append({"error": "At least one explicit manifest path is required"})
    for supplied in paths:
        path = Path(supplied).resolve()
        manifest = str(path)
        try:
            raw = path.read_bytes()
            document = json.loads(raw)
            collection, records = _records(document)
        except (OSError, ValueError, UnicodeError) as exc:
            errors.append({"manifest": manifest, "error": str(exc)})
            continue
        manifests.append({"path": manifest, "sha256": hashlib.sha256(raw).hexdigest(),
                          "collection": collection, "record_count": len(records)})
        seen = set()
        for index, record in enumerate(records):
            try:
                alias = _alias(record, collection, manifest, index)
                if alias["id"] in seen:
                    raise ValueError("Duplicate record ID in manifest")
                seen.add(alias["id"])
            except ValueError as exc:
                errors.append({"manifest": manifest, "record_index": index, "error": str(exc)})
                continue
            if alias["sha256"] is None:
                unknown.append(alias)
            else:
                aliases_by_hash[alias["sha256"]].append(alias)
    groups = [{"sha256": sha, "aliases": aliases,
               "splits": sorted({alias["split"] for alias in aliases})}
              for sha, aliases in sorted(aliases_by_hash.items())]
    conflicts = [group for group in groups if len(group["splits"]) > 1]
    if errors or conflicts:
        status = "blocked"
    elif unknown or not groups:
        status = "incomplete"
    else:
        status = "passed"
    return {
        "schema_version": 1,
        "report_type": "source_sha_split_preflight",
        "passed": status == "passed",
        "status": status,
        "scope": "Declared exact source SHA-256 only; no source-image reads, historical exposure or release acceptance certification",
        "manifests": manifests,
        "summary": {"unique_source_hashes": len(groups), "conflict_count": len(conflicts),
                    "unknown_hash_count": len(unknown), "error_count": len(errors)},
        "conflicts": conflicts,
        "shared_sources": [group for group in groups if len(group["aliases"]) > 1],
        "unknown_hashes": unknown,
        "errors": errors,
    }
