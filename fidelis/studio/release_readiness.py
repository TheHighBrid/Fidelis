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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence


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
REVIEW_OR_DONE_STATES: frozenset[str] = frozenset(
    {"In Review", "Done", "Completed", "Released"}
)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_valid_git_sha(value: Any) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"[0-9a-f]{7,40}", value.strip()))


def evaluate_release_readiness(
    backlog_data: Mapping[str, Any],
    *,
    release_manifest: Mapping[str, Any] | None = None,
    repo_root: str | Path | None = None,
) -> dict[str, Any]:
    """Evaluate production release readiness (`F16` / `MEL-68`) against `QUALITY_GATES.md`."""
    manifest = dict(release_manifest or {})
    items = backlog_data.get("items") or []
    by_id: dict[str, Mapping[str, Any]] = {
        str(item.get("id")): item
        for item in items
        if isinstance(item, Mapping) and item.get("id")
    }

    blocking_reasons: list[str] = []

    # 1. Core feature milestone tasks (F01..F15)
    core_tasks: list[dict[str, Any]] = []
    unfinished_core_ids: list[str] = []
    for task_id in CORE_RELEASE_TASK_IDS:
        item = by_id.get(task_id, {})
        state = str(item.get("state", "missing"))
        impl = str(item.get("implementation", "missing"))
        linear_id = str((item.get("linear") or {}).get("id", ""))
        is_closed = state in DONE_STATES
        if not is_closed:
            unfinished_core_ids.append(task_id)
        core_tasks.append(
            {
                "id": task_id,
                "linear_id": linear_id,
                "title": str(item.get("title", "")),
                "state": state,
                "implementation": impl,
                "closed": is_closed,
            }
        )
    if unfinished_core_ids:
        blocking_reasons.append("unfinished_core_deliverables")

    # 2. Blocking audit defects (D01..D04)
    defect_tasks: list[dict[str, Any]] = []
    open_defect_ids: list[str] = []
    unmerged_defect_ids: list[str] = []
    for defect_id in BLOCKING_DEFECT_IDS:
        item = by_id.get(defect_id, {})
        state = str(item.get("state", "missing"))
        impl = str(item.get("implementation", "missing"))
        linear_id = str((item.get("linear") or {}).get("id", ""))
        is_closed = state in DONE_STATES
        is_in_review = state in REVIEW_OR_DONE_STATES
        if not is_in_review:
            open_defect_ids.append(defect_id)
        elif not is_closed:
            unmerged_defect_ids.append(defect_id)
        defect_tasks.append(
            {
                "id": defect_id,
                "linear_id": linear_id,
                "title": str(item.get("title", "")),
                "state": state,
                "implementation": impl,
                "closed": is_closed,
            }
        )
    if open_defect_ids or unmerged_defect_ids:
        blocking_reasons.append("blocking_defects_not_closed_on_main")

    # 3. Release SHA & target branch merge status
    release_sha = manifest.get("release_sha")
    merged_to_main = bool(manifest.get("merged_to_main", False))
    sha_valid = _is_valid_git_sha(release_sha)
    if not sha_valid or not merged_to_main:
        blocking_reasons.append("release_sha_or_main_merge_unverified")

    # 4. Package artifacts & SHA-256 verification
    raw_packages = manifest.get("packages")
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

        file_verified = False
        file_present = False
        if root_path is not None:
            candidate = (root_path / rel_path).resolve()
            if not candidate.is_relative_to(root_path):
                package_errors.append(
                    f"package {rel_path}: path escapes repository root"
                )
            elif candidate.is_file():
                file_present = True
                actual_sha = _sha256_file(candidate)
                if actual_sha == declared_sha:
                    file_verified = True
                else:
                    package_errors.append(
                        f"package {rel_path}: sha256 mismatch ({actual_sha} != {declared_sha})"
                    )
            else:
                package_errors.append(f"package {rel_path}: file missing on disk")
        else:
            package_errors.append(f"package {rel_path}: no artifact root supplied")

        verified_packages.append(
            {
                "path": rel_path,
                "sha256": declared_sha,
                "verified": file_verified,
                "file_present": file_present,
            }
        )

    if package_errors:
        blocking_reasons.append("release_packages_unverified")

    # 5. Held-out quality & operational gate evidence
    quality_gate = manifest.get("quality_gate") or {}
    quality_accepted = quality_gate.get("overall_status") == "accepted" and bool(
        quality_gate.get("report_sha256")
    )
    if not quality_accepted:
        blocking_reasons.append("held_out_quality_gate_not_accepted")

    operational_gate = manifest.get("operational_gate") or {}
    ops_verified = (
        bool(operational_gate.get("live_worker_verified", False))
        and bool(operational_gate.get("device_budgets_measured", False))
        and bool(operational_gate.get("upgrade_rollback_verified", False))
    )
    if not ops_verified:
        blocking_reasons.append("operational_and_device_gates_incomplete")

    # 6. Explicit scope, known limits, and rollback runbook
    scope_summary = str(manifest.get("scope_summary", "")).strip()
    known_limits = manifest.get("known_limits")
    rollback_plan = manifest.get("rollback_plan") or {}
    rollback_ready = (
        bool(rollback_plan.get("snapshot_command"))
        and bool(rollback_plan.get("restore_command"))
        and bool(rollback_plan.get("previous_stable_tag_or_sha"))
    )
    if (
        not scope_summary
        or not isinstance(known_limits, Sequence)
        or isinstance(known_limits, (str, bytes))
        or len(known_limits) == 0
        or not rollback_ready
    ):
        blocking_reasons.append("scope_limits_or_rollback_plan_incomplete")

    # 7. Owner creative and release signoff
    signoff = manifest.get("owner_release_signoff") or {}
    signoff_status = str(signoff.get("status", "pending")).strip()
    owner_approved = (
        signoff_status == "approved"
        and bool(signoff.get("creative_owner"))
        and bool(signoff.get("release_owner"))
        and bool(signoff.get("signed_at"))
    )
    if not owner_approved:
        blocking_reasons.append("owner_release_signoff_missing")

    # Determine highest certified evidence level (E0..E4)
    if len(blocking_reasons) == 0:
        evidence_level = "E4_released"
        overall_status = "ready_for_release"
    elif quality_accepted and ops_verified:
        evidence_level = "E3_visually_and_device_accepted"
        overall_status = "awaiting_release_packaging_or_signoff"
    elif bool(operational_gate.get("live_worker_verified", False)):
        evidence_level = "E2_live_inference_verified"
        overall_status = "blocked_release_gates"
    else:
        evidence_level = "E1_fixture_and_protocol_tested"
        overall_status = "blocked_release_gates"

    dossier = {
        "schema_version": SCHEMA_VERSION,
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "overall_status": overall_status,
        "certified_evidence_level": evidence_level,
        "ready_for_release": len(blocking_reasons) == 0,
        "blocking_reasons": blocking_reasons,
        "release_sha": release_sha,
        "merged_to_main": merged_to_main,
        "core_deliverables": {
            "total": len(CORE_RELEASE_TASK_IDS),
            "closed_count": len(CORE_RELEASE_TASK_IDS) - len(unfinished_core_ids),
            "unfinished_ids": unfinished_core_ids,
            "tasks": core_tasks,
        },
        "blocking_defects": {
            "total": len(BLOCKING_DEFECT_IDS),
            "open_ids": open_defect_ids,
            "unmerged_in_review_ids": unmerged_defect_ids,
            "defects": defect_tasks,
        },
        "packages": {
            "verified_count": sum(1 for p in verified_packages if p["verified"]),
            "on_disk_verified_count": sum(
                1 for p in verified_packages if p["verified"] and p["file_present"]
            ),
            "items": verified_packages,
            "errors": package_errors,
        },
        "quality_gate": {
            "accepted": quality_accepted,
            "overall_status": quality_gate.get("overall_status", "missing"),
            "report_sha256": quality_gate.get("report_sha256"),
        },
        "operational_gate": {
            "verified": ops_verified,
            "live_worker_verified": bool(
                operational_gate.get("live_worker_verified", False)
            ),
            "device_budgets_measured": bool(
                operational_gate.get("device_budgets_measured", False)
            ),
            "upgrade_rollback_verified": bool(
                operational_gate.get("upgrade_rollback_verified", False)
            ),
        },
        "documentation_and_rollback": {
            "scope_summary_present": bool(scope_summary),
            "known_limits_count": (
                len(known_limits)
                if isinstance(known_limits, Sequence)
                and not isinstance(known_limits, (str, bytes))
                else 0
            ),
            "rollback_ready": rollback_ready,
        },
        "owner_release_signoff": {
            "status": signoff_status,
            "approved": owner_approved,
            "creative_owner": signoff.get("creative_owner"),
            "release_owner": signoff.get("release_owner"),
            "signed_at": signoff.get("signed_at"),
        },
    }
    dossier["dossier_sha256"] = hashlib.sha256(
        json.dumps(dossier, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return dossier
