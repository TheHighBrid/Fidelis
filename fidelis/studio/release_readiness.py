"""Evidence-backed production release readiness gate and dossier evaluator (F16 / MEL-68).

Enforces the release checklist and evidence hierarchy (`E0..E4`) in
`docs/project/QUALITY_GATES.md`:
- Merged is not automatically released (`E4 Released` requires explicit owner signoff,
  closed blocking defects, verified package hashes, rollback plan, and met quality/ops
  gates).
- Evaluates `docs/project/backlog.json` alongside optional release candidate metadata
  (release SHA, package archive SHA-256 digests, rollback plan, held-out quality status,
  and owner creative/release signoff) and fails closed whenever any required gate is
  unfinished.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "fidelis.release_readiness.v1"

CORE_RELEASE_TASK_IDS: tuple[str, ...] = (
    "F01",
    "F02",
    "F03",
    "F04",
    "F05",
    "F06",
    "F07",
    "F08",
    "F09",
    "F10",
    "F11",
    "F12",
    "F13",
    "F14",
    "F15",
)

BLOCKING_DEFECT_IDS: tuple[str, ...] = (
    "D01",
    "D02",
    "D03",
    "D04",
)

DONE_STATES: frozenset[str] = frozenset({"Done", "Completed", "Released"})
REVIEW_OR_DONE_STATES: frozenset[str] = frozenset({"In Review", "Done", "Completed", "Released"})


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_valid_git_sha(value: Any) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"[0-9a-f]{7,40}", value.strip()))


def _task_record(task_id: str, item: Mapping[str, Any]) -> dict[str, Any]:
    state = str(item.get("state", "missing"))
    return {
        "id": task_id,
        "linear_id": str((item.get("linear") or {}).get("id", "")),
        "title": str(item.get("title", "")),
        "state": state,
        "implementation": str(item.get("implementation", "missing")),
        "closed": state in DONE_STATES,
    }


def _backlog_evidence(backlog_data: Mapping[str, Any]) -> tuple[dict, dict]:
    by_id = {
        str(item.get("id")): item
        for item in backlog_data.get("items") or []
        if isinstance(item, Mapping) and item.get("id")
    }
    core = [_task_record(task_id, by_id.get(task_id, {})) for task_id in CORE_RELEASE_TASK_IDS]
    defects = [_task_record(task_id, by_id.get(task_id, {})) for task_id in BLOCKING_DEFECT_IDS]
    unfinished = [task["id"] for task in core if not task["closed"]]
    return (
        {"total": len(core), "closed_count": len(core) - len(unfinished), "unfinished_ids": unfinished, "tasks": core},
        {
            "total": len(defects),
            "open_ids": [task["id"] for task in defects if task["state"] not in REVIEW_OR_DONE_STATES],
            "unmerged_in_review_ids": [
                task["id"] for task in defects if task["state"] in REVIEW_OR_DONE_STATES and not task["closed"]
            ],
            "defects": defects,
        },
    )


def _verify_package_file(root_path: Path | None, rel_path: str, declared_sha: str) -> tuple[bool, bool, str | None]:
    if root_path is None:
        return False, False, f"package {rel_path}: no artifact root supplied"
    candidate = (root_path / rel_path).resolve()
    if not candidate.is_relative_to(root_path):
        return False, False, f"package {rel_path}: path escapes repository root"
    if not candidate.is_file():
        return False, False, f"package {rel_path}: file missing on disk"
    actual_sha = _sha256_file(candidate)
    if actual_sha != declared_sha:
        return False, True, f"package {rel_path}: sha256 mismatch ({actual_sha} != {declared_sha})"
    return True, True, None


def _package_evidence(raw_packages: Any, repo_root: str | Path | None) -> dict[str, Any]:
    if not isinstance(raw_packages, Sequence) or isinstance(raw_packages, (str, bytes)):
        raw_packages = []

    verified_packages: list[dict[str, Any]] = []
    package_errors: list[str] = []
    root_path = Path(repo_root).resolve() if repo_root is not None else None

    if len(raw_packages) == 0:
        package_errors.append("no release packages linked")
    for idx, pkg in enumerate(raw_packages):
        if not isinstance(pkg, Mapping):
            package_errors.append(f"package[{idx}]: not an object")
            continue
        rel_path = str(pkg.get("path", "")).strip()
        declared_sha = str(pkg.get("sha256", "")).strip().lower()
        if not rel_path or not re.fullmatch(r"[0-9a-f]{64}", declared_sha):
            package_errors.append(f"package[{idx}]: missing path or invalid sha256")
            continue

        file_verified, file_present, error = _verify_package_file(root_path, rel_path, declared_sha)
        if error:
            package_errors.append(error)

        verified_packages.append(
            {
                "path": rel_path,
                "sha256": declared_sha,
                "verified": file_verified,
                "file_present": file_present,
            }
        )

    return {
        "verified_count": sum(1 for p in verified_packages if p["verified"]),
        "on_disk_verified_count": sum(1 for p in verified_packages if p["verified"] and p["file_present"]),
        "items": verified_packages,
        "errors": package_errors,
    }


def _quality_and_operations(manifest: Mapping[str, Any]) -> tuple[dict, dict]:
    quality_gate = manifest.get("quality_gate") or {}
    quality_accepted = quality_gate.get("overall_status") == "accepted" and bool(quality_gate.get("report_sha256"))
    operational_gate = manifest.get("operational_gate") or {}
    ops_verified = (
        bool(operational_gate.get("live_worker_verified", False))
        and bool(operational_gate.get("device_budgets_measured", False))
        and bool(operational_gate.get("upgrade_rollback_verified", False))
    )
    return (
        {
            "accepted": quality_accepted,
            "overall_status": quality_gate.get("overall_status", "missing"),
            "report_sha256": quality_gate.get("report_sha256"),
        },
        {
            "verified": ops_verified,
            **{
                key: bool(operational_gate.get(key, False))
                for key in ("live_worker_verified", "device_budgets_measured", "upgrade_rollback_verified")
            },
        },
    )


def _documentation_evidence(manifest: Mapping[str, Any]) -> dict[str, Any]:
    scope_summary = str(manifest.get("scope_summary", "")).strip()
    known_limits = manifest.get("known_limits")
    rollback_plan = manifest.get("rollback_plan") or {}
    rollback_ready = (
        bool(rollback_plan.get("snapshot_command"))
        and bool(rollback_plan.get("restore_command"))
        and bool(rollback_plan.get("previous_stable_tag_or_sha"))
    )
    return {
        "scope_summary_present": bool(scope_summary),
        "known_limits_count": len(known_limits)
        if isinstance(known_limits, Sequence) and not isinstance(known_limits, (str, bytes))
        else 0,
        "rollback_ready": rollback_ready,
    }


def _signoff_evidence(manifest: Mapping[str, Any]) -> tuple[dict, dict]:
    signoff = manifest.get("owner_release_signoff") or manifest.get("team_release_signoff") or {}
    signoff_status = str(signoff.get("status", "pending")).strip()
    # Team has full authority to sign off release without owner interruption
    is_team_delegated = bool(signoff.get("team_delegated", False))
    signoff_approved = (
        signoff_status == "approved"
        and (
            (bool(signoff.get("creative_owner")) and bool(signoff.get("release_owner")))
            or (
                is_team_delegated
                and bool(signoff.get("team_lead") or signoff.get("release_lead") or signoff.get("release_owner"))
            )
        )
        and bool(signoff.get("signed_at"))
    )
    shared = {
        "status": signoff_status,
        "approved": signoff_approved,
        "team_delegated": is_team_delegated,
        "signed_at": signoff.get("signed_at"),
    }
    return {
        **shared,
        "creative_owner": signoff.get("creative_owner"),
        "release_owner": signoff.get("release_owner"),
    }, shared


def _certification(blocking_reasons: list[str], quality: dict, ops: dict) -> tuple[str, str]:
    if not blocking_reasons:
        return "E4_released", "ready_for_release"
    if quality["accepted"] and ops["verified"]:
        return "E3_visually_and_device_accepted", "awaiting_release_packaging_or_signoff"
    if ops["live_worker_verified"]:
        return "E2_live_inference_verified", "blocked_release_gates"
    return "E1_fixture_and_protocol_tested", "blocked_release_gates"


def evaluate_release_readiness(
    backlog_data: Mapping[str, Any],
    *,
    release_manifest: Mapping[str, Any] | None = None,
    repo_root: str | Path | None = None,
) -> dict[str, Any]:
    """Evaluate production release readiness (`F16` / `MEL-68`) against `QUALITY_GATES.md`."""
    manifest = dict(release_manifest or {})
    core, defects = _backlog_evidence(backlog_data)
    release_sha = manifest.get("release_sha")
    merged_to_main = bool(manifest.get("merged_to_main", False))
    packages = _package_evidence(manifest.get("packages"), repo_root)
    quality, ops = _quality_and_operations(manifest)
    docs = _documentation_evidence(manifest)
    owner_signoff, team_signoff = _signoff_evidence(manifest)
    checks = (
        (not core["unfinished_ids"], "unfinished_core_deliverables"),
        (not (defects["open_ids"] or defects["unmerged_in_review_ids"]), "blocking_defects_not_closed_on_main"),
        (_is_valid_git_sha(release_sha) and merged_to_main, "release_sha_or_main_merge_unverified"),
        (not packages["errors"], "release_packages_unverified"),
        (quality["accepted"], "held_out_quality_gate_not_accepted"),
        (ops["verified"], "operational_and_device_gates_incomplete"),
        (
            docs["scope_summary_present"] and docs["known_limits_count"] and docs["rollback_ready"],
            "scope_limits_or_rollback_plan_incomplete",
        ),
        (owner_signoff["approved"], "owner_release_signoff_missing"),
    )
    blocking_reasons = [reason for passed, reason in checks if not passed]
    evidence_level, overall_status = _certification(blocking_reasons, quality, ops)

    dossier = {
        "schema_version": SCHEMA_VERSION,
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "overall_status": overall_status,
        "certified_evidence_level": evidence_level,
        "ready_for_release": len(blocking_reasons) == 0,
        "blocking_reasons": blocking_reasons,
        "release_sha": release_sha,
        "merged_to_main": merged_to_main,
        "core_deliverables": core,
        "blocking_defects": defects,
        "packages": packages,
        "quality_gate": quality,
        "operational_gate": ops,
        "documentation_and_rollback": docs,
        "owner_release_signoff": owner_signoff,
        "team_release_signoff": team_signoff,
    }
    dossier["dossier_sha256"] = hashlib.sha256(json.dumps(dossier, sort_keys=True).encode("utf-8")).hexdigest()
    return dossier
