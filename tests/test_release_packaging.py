"""Unit tests for release archive auditing and workspace upgrade/rollback protection (F15 / MEL-69)."""

from __future__ import annotations

import json
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

import numpy as np

from fidelis.postprocess.regions import RegionBlend
from fidelis.studio.packaging import (
    REQUIRED_ARCHIVE_PATHS,
    audit_release_archive,
    create_workspace_snapshot,
    restore_workspace_snapshot,
    verify_workspace_integrity,
)
from fidelis.studio.store import JobStore


REPO_ROOT = Path(__file__).resolve().parent.parent


class ReleasePackagingAndUpgradeTests(unittest.TestCase):
    def test_audit_release_archive_flags_missing_modules_and_forbidden_leaks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive_path = root / "sample.tar.gz"

            with tarfile.open(archive_path, "w:gz") as tar:
                for rel in REQUIRED_ARCHIVE_PATHS[:-1]:
                    src = root / "payload" / rel
                    src.parent.mkdir(parents=True, exist_ok=True)
                    src.write_text("# stub\n", encoding="utf-8")
                    tar.add(src, arcname=rel)

                leaked = root / "payload" / ".cache" / "web_outputs" / "secret.npy"
                leaked.parent.mkdir(parents=True, exist_ok=True)
                leaked.write_bytes(b"leak")
                tar.add(leaked, arcname=".cache/web_outputs/secret.npy")

                env_file = root / "payload" / ".env.production"
                env_file.write_text("SECRET=1\n", encoding="utf-8")
                tar.add(env_file, arcname=".env.production")

            report = audit_release_archive(archive_path)
            self.assertFalse(report["passed"])
            self.assertEqual(report["missing_required"], [REQUIRED_ARCHIVE_PATHS[-1]])
            reasons = {item["path"]: item["reason"] for item in report["forbidden_matches"]}
            self.assertIn(".cache/web_outputs/secret.npy", reasons)
            self.assertEqual(reasons[".env.production"], "forbidden_env_file")

    def test_clean_release_archive_passes_audit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive_path = root / "clean.tar.gz"
            with tarfile.open(archive_path, "w:gz") as tar:
                for rel in REQUIRED_ARCHIVE_PATHS:
                    src = root / "payload" / rel
                    src.parent.mkdir(parents=True, exist_ok=True)
                    src.write_text("# ok\n", encoding="utf-8")
                    tar.add(src, arcname=f"fidelis-offline-bundle-v3.0.0/{rel}")

            report = audit_release_archive(archive_path, strip_top_level=True)
            self.assertTrue(report["passed"])
            self.assertEqual(report["missing_required"], [])
            self.assertEqual(report["forbidden_matches"], [])

    def test_workspace_snapshot_upgrade_and_atomic_rollback_preserves_jobs_and_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            region_root = root / "region_jobs"
            gen_root = root / "generation_runs"
            snapshot_dir = root / "snapshots" / "pre-v3.1.0"

            store = JobStore(region_root)
            base = np.full((24, 24, 3), [30, 60, 90], dtype=np.uint8)
            texture = np.full((24, 24, 3), [140, 160, 180], dtype=np.uint8)
            skin = np.zeros((24, 24), dtype=np.float32)
            skin[4:16, 4:16] = 1.0
            protect = np.zeros((24, 24), dtype=np.float32)
            protect[0:6, 0:6] = 1.0

            job = store.create(
                base,
                texture,
                masks={"skin": skin, "protected": protect},
                blend=RegionBlend(skin=0.75, hair=0.5, fabric=0.25),
                label="Editorial Upgrade Anchor",
                profile="luxury_apparel",
            )
            job_id = job["id"]
            with store.open_array(job_id, "master") as arr:
                original_master = np.array(arr, copy=True)

            runs_dir = gen_root / "runs"
            runs_dir.mkdir(parents=True, exist_ok=True)
            run_id = "a" * 32
            run_record = {
                "schema_version": 1,
                "id": run_id,
                "job_id": job_id,
                "base_revision": 1,
                "status": "succeeded",
                "created_at": "2026-11-10T15:00:00+00:00",
            }
            (runs_dir / f"{run_id}.json").write_text(
                json.dumps(run_record, indent=2) + "\n", encoding="utf-8"
            )

            pre_verify = verify_workspace_integrity(region_root, gen_root)
            self.assertTrue(pre_verify["passed"])
            self.assertEqual(pre_verify["job_count"], 1)
            self.assertEqual(pre_verify["generation_run_count"], 1)

            snap = create_workspace_snapshot(
                region_root,
                snapshot_dir,
                generation_root=gen_root,
                target_version="3.1.0",
            )
            self.assertEqual(
                snap["integrity"]["state_fingerprint"], pre_verify["state_fingerprint"]
            )

            # Simulate post-snapshot mutation during an upgrade that we then roll back
            updated = store.reblend(
                job_id,
                expected_revision=1,
                blend=RegionBlend(skin=0.1, hair=0.1, fabric=0.1),
            )
            self.assertEqual(updated["revision"], 2)
            (runs_dir / f"{run_id}.json").unlink()

            mutated_verify = verify_workspace_integrity(region_root, gen_root)
            self.assertNotEqual(
                mutated_verify["state_fingerprint"], pre_verify["state_fingerprint"]
            )

            restored = restore_workspace_snapshot(
                snapshot_dir,
                region_root,
                generation_root=gen_root,
            )
            self.assertEqual(
                restored["state_fingerprint"], pre_verify["state_fingerprint"]
            )

            reopened = JobStore(region_root)
            restored_job = reopened.get(job_id)
            self.assertEqual(restored_job["revision"], 1)
            self.assertEqual(restored_job["label"], "Editorial Upgrade Anchor")
            with reopened.open_array(job_id, "master") as arr:
                restored_master = np.array(arr, copy=True)
            np.testing.assert_array_equal(restored_master, original_master)
            self.assertTrue((runs_dir / f"{run_id}.json").is_file())

    def test_verify_workspace_detects_corrupted_artifact_and_cli_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            region_root = root / "region_jobs"
            snap_dir = root / "snap"

            store = JobStore(region_root)
            base = np.zeros((16, 16, 3), dtype=np.uint8)
            job = store.create(base, base, label="CLI Check")

            script = REPO_ROOT / "scripts" / "verify-upgrade-rollback.py"
            proc_snap = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "snapshot",
                    "--region-root",
                    str(region_root),
                    "--snapshot-dir",
                    str(snap_dir),
                    "--target-version",
                    "3.0.1",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(proc_snap.returncode, 0, msg=proc_snap.stderr)

            # Corrupt an artifact byte on disk
            master_rel = job["artifacts"]["master"]["path"]
            master_path = region_root / master_rel
            data = bytearray(master_path.read_bytes())
            data[-1] ^= 0xFF
            master_path.write_bytes(bytes(data))

            proc_verify_bad = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "verify-workspace",
                    "--region-root",
                    str(region_root),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(proc_verify_bad.returncode, 2)
            bad_payload = json.loads(proc_verify_bad.stdout)
            self.assertFalse(bad_payload["passed"])
            self.assertTrue(any("sha256 mismatch" in err for err in bad_payload["errors"]))

            proc_restore = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "restore",
                    "--snapshot-dir",
                    str(snap_dir),
                    "--region-root",
                    str(region_root),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(proc_restore.returncode, 0, msg=proc_restore.stderr)

            proc_verify_ok = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "verify-workspace",
                    "--region-root",
                    str(region_root),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(proc_verify_ok.returncode, 0, msg=proc_verify_ok.stderr)


if __name__ == "__main__":
    unittest.main()
