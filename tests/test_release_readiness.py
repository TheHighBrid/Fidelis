"""Unit tests for evidence-backed production release readiness auditing (F16 / MEL-68)."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from fidelis.studio.release_readiness import (
    BLOCKING_DEFECT_IDS,
    CORE_RELEASE_TASK_IDS,
    evaluate_release_readiness,
)


REPO_ROOT = Path(__file__).resolve().parent.parent


def _make_closed_backlog() -> dict:
    items = []
    for task_id in CORE_RELEASE_TASK_IDS:
        items.append(
            {
                "id": task_id,
                "title": f"Task {task_id}",
                "state": "Done",
                "implementation": "verified",
                "linear": {"id": f"MEL-{task_id}"},
            }
        )
    for defect_id in BLOCKING_DEFECT_IDS:
        items.append(
            {
                "id": defect_id,
                "title": f"Defect {defect_id}",
                "state": "Done",
                "implementation": "verified",
                "linear": {"id": f"MEL-{defect_id}"},
            }
        )
    return {"items": items}


def _make_complete_manifest(pkg_path: str, pkg_sha: str, *, signed: bool = True) -> dict:
    return {
        "release_sha": "f84287993c9bc213dc47859b297a5a275381101d",
        "merged_to_main": True,
        "packages": [
            {
                "path": pkg_path,
                "sha256": pkg_sha,
                "require_file_present": True,
            }
        ],
        "quality_gate": {
            "overall_status": "accepted",
            "report_sha256": "a" * 64,
        },
        "operational_gate": {
            "live_worker_verified": True,
            "device_budgets_measured": True,
            "upgrade_rollback_verified": True,
        },
        "scope_summary": "Fidelis Studio v3.1 local regional restoration release",
        "known_limits": [
            "Local loopback binding only (127.0.0.1); not a public cloud service.",
            " Provenance manifests are unsigned execution records unless signed by an external X.509 C2PA certificate.",
        ],
        "rollback_plan": {
            "previous_stable_tag_or_sha": "5315046",
            "snapshot_command": ".venv/bin/python scripts/verify-upgrade-rollback.py snapshot ...",
            "restore_command": ".venv/bin/python scripts/verify-upgrade-rollback.py restore ...",
        },
        "owner_release_signoff": {
            "status": "approved" if signed else "pending",
            "creative_owner": "Creative Lead" if signed else None,
            "release_owner": "Release Lead" if signed else None,
            "signed_at": "2026-11-10T16:15:00Z" if signed else None,
        },
    }


class ReleaseReadinessTests(unittest.TestCase):
    def test_tracked_repository_backlog_is_honestly_blocked_at_e1(self) -> None:
        backlog_data = json.loads(
            (REPO_ROOT / "docs" / "project" / "backlog.json").read_text(encoding="utf-8")
        )
        dossier = evaluate_release_readiness(backlog_data, repo_root=REPO_ROOT)
        self.assertFalse(dossier["ready_for_release"])
        self.assertEqual(dossier["overall_status"], "blocked_release_gates")
        self.assertEqual(
            dossier["certified_evidence_level"], "E1_fixture_and_protocol_tested"
        )
        self.assertIn("unfinished_core_deliverables", dossier["blocking_reasons"])
        self.assertIn("blocking_defects_not_closed_on_main", dossier["blocking_reasons"])
        self.assertIn("held_out_quality_gate_not_accepted", dossier["blocking_reasons"])
        self.assertIn("owner_release_signoff_missing", dossier["blocking_reasons"])

    def test_complete_evidence_and_signoff_reaches_e4_released(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pkg = root / "dist" / "fidelis-v3.1.0.tar.gz"
            pkg.parent.mkdir(parents=True, exist_ok=True)
            payload = b"fidelis-release-archive-bytes"
            pkg.write_bytes(payload)
            pkg_sha = hashlib.sha256(payload).hexdigest()

            backlog = _make_closed_backlog()
            manifest_unsigned = _make_complete_manifest(
                "dist/fidelis-v3.1.0.tar.gz", pkg_sha, signed=False
            )
            dossier_unsigned = evaluate_release_readiness(
                backlog, release_manifest=manifest_unsigned, repo_root=root
            )
            self.assertFalse(dossier_unsigned["ready_for_release"])
            self.assertEqual(
                dossier_unsigned["certified_evidence_level"],
                "E3_visually_and_device_accepted",
            )
            self.assertEqual(
                dossier_unsigned["blocking_reasons"], ["owner_release_signoff_missing"]
            )

            manifest_signed = _make_complete_manifest(
                "dist/fidelis-v3.1.0.tar.gz", pkg_sha, signed=True
            )
            dossier_signed = evaluate_release_readiness(
                backlog, release_manifest=manifest_signed, repo_root=root
            )
            self.assertTrue(dossier_signed["ready_for_release"])
            self.assertEqual(dossier_signed["overall_status"], "ready_for_release")
            self.assertEqual(dossier_signed["certified_evidence_level"], "E4_released")
            self.assertEqual(dossier_signed["blocking_reasons"], [])

    def test_package_checksum_mismatch_or_unmerged_sha_blocks_release(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pkg = root / "dist" / "fidelis-v3.1.0.tar.gz"
            pkg.parent.mkdir(parents=True, exist_ok=True)
            pkg.write_bytes(b"actual-bytes")
            wrong_sha = "0" * 64

            backlog = _make_closed_backlog()
            manifest = _make_complete_manifest(
                "dist/fidelis-v3.1.0.tar.gz", wrong_sha, signed=True
            )
            manifest["merged_to_main"] = False
            dossier = evaluate_release_readiness(
                backlog, release_manifest=manifest, repo_root=root
            )
            self.assertFalse(dossier["ready_for_release"])
            self.assertIn(
                "release_sha_or_main_merge_unverified", dossier["blocking_reasons"]
            )
            self.assertIn("release_packages_unverified", dossier["blocking_reasons"])

    def test_cli_exit_code_fails_closed_by_default_and_supports_allow_blocked(self) -> None:
        script = REPO_ROOT / "scripts" / "audit-release-readiness.py"
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "dossier.json"
            proc_strict = subprocess.run(
                [sys.executable, str(script), "--output", str(out_path)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(proc_strict.returncode, 2)
            saved = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertFalse(saved["ready_for_release"])

            proc_allow = subprocess.run(
                [sys.executable, str(script), "--allow-blocked"],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(proc_allow.returncode, 0, msg=proc_allow.stderr)

    def test_tracked_release_candidate_manifest_verifies_packages_and_rollback(self) -> None:
        backlog_data = json.loads(
            (REPO_ROOT / "docs" / "project" / "backlog.json").read_text(encoding="utf-8")
        )
        manifest_path = REPO_ROOT / "config" / "release-candidate-v1.json"
        self.assertTrue(manifest_path.is_file())
        manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
        dossier = evaluate_release_readiness(
            backlog_data,
            release_manifest=manifest_data,
            repo_root=REPO_ROOT,
        )
        self.assertFalse(dossier["ready_for_release"])
        self.assertEqual(
            dossier["certified_evidence_level"], "E1_fixture_and_protocol_tested"
        )
        self.assertEqual(dossier["packages"]["verified_count"], 3)
        self.assertEqual(dossier["packages"]["errors"], [])
        self.assertTrue(dossier["documentation_and_rollback"]["scope_summary_present"])
        self.assertGreaterEqual(
            dossier["documentation_and_rollback"]["known_limits_count"], 4
        )
        self.assertTrue(dossier["documentation_and_rollback"]["rollback_ready"])
        self.assertTrue(dossier["operational_gate"]["device_budgets_measured"])
        self.assertTrue(dossier["operational_gate"]["upgrade_rollback_verified"])
        self.assertFalse(dossier["operational_gate"]["live_worker_verified"])
        self.assertNotIn("release_packages_unverified", dossier["blocking_reasons"])
        self.assertNotIn(
            "scope_limits_or_rollback_plan_incomplete", dossier["blocking_reasons"]
        )


if __name__ == "__main__":
    unittest.main()
