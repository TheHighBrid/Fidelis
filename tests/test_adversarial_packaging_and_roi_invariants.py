"""Adversarial stress-testing suite for Fidelis Packaging SQLite Snapshots and Restoration Runner Invariants.

Adversarially challenges:
1. fidelis/studio/packaging.py:
   - Workspace integrity and snapshot verification with empty SQLite databases.
   - Missing tables (e.g., missing jobs table in jobs.sqlite3).
   - Column variation: table 'runs' with column 'id' vs 'run_id' vs both vs neither.
   - Handling of locked databases (concurrent exclusive lock).
   - Detection of corrupted SQLite files (garbage header, truncated, invalid JSON records, hash mismatch).
   - Snapshot inclusion and atomic restoration of all *.sqlite3 ledgers in root and runs/.
   - Fail-closed behavior on corrupted workspaces and tampered snapshot manifests.

2. fidelis/engine/restoration_runner.py:
   - Empty ROIs strictly fall back to 100% bitwise identical base image.
   - Preservation-only ROIs strictly fall back to 100% bitwise identical base image.
   - Unclassified pixels outside partial texture ROIs remain 100% bitwise identical to base image.
   - Negative coordinates, negative dimensions, and out-of-bounds ROI handling.
   - Full-image ROIs under preserve, texture_allowed, lock, and unlock override combinations.
   - Invariant: Explicit protection wins over semantic texture in overlapping regions.
   - Invariant: ComfyRestorationBackend workflow_sha256 vs weights_sha256 provenance separation.
   - Input validation and fail-closed error handling (dtypes, dimensions, scales).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

from fidelis.engine import (
    ComfyRestorationBackend,
    DimensionMismatchError,
    RestorationRunner,
    create_restoration_runner,
)
from fidelis.postprocess.regions import RegionBlend
from fidelis.studio.packaging import (
    create_workspace_snapshot,
    restore_workspace_snapshot,
    verify_workspace_integrity,
)


def _make_test_rgb(h: int = 16, w: int = 16, seed: int = 101) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.integers(15, 235, size=(h, w, 3), dtype=np.uint8)


class AdversarialPackagingSQLiteSnapshotTests(unittest.TestCase):
    """Stress tests for fidelis/studio/packaging.py workspace snapshot and SQLite ledger verification."""

    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory(prefix="adv_pack_")
        self.addCleanup(self.tmp_dir.cleanup)
        self.root = Path(self.tmp_dir.name)
        self.r_root = self.root / "region_jobs"
        self.g_root = self.root / "generation_runs"
        self.r_root.mkdir()
        self.g_root.mkdir()

    def _init_valid_jobs_db(self) -> Path:
        db_path = self.r_root / "jobs.sqlite3"
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE jobs (id TEXT PRIMARY KEY, manifest TEXT NOT NULL)")
        conn.commit()
        conn.close()
        return db_path

    def test_verify_empty_jobs_db_missing_table_fails_gracefully(self) -> None:
        """When jobs.sqlite3 exists but is 0-byte or lacks 'jobs' table, integrity check reports failure."""
        db_path = self.r_root / "jobs.sqlite3"
        conn = sqlite3.connect(db_path)
        conn.close()  # creates empty 0-table database

        res = verify_workspace_integrity(self.r_root)
        self.assertFalse(res["passed"])
        self.assertTrue(any("no such table: jobs" in err for err in res["errors"]))

        # Refusal to snapshot corrupted workspace
        snap_dir = self.root / "snapshots" / "fail_snap"
        with self.assertRaises(ValueError) as ctx:
            create_workspace_snapshot(self.r_root, snap_dir)
        self.assertIn("Refusing to snapshot corrupted workspace", str(ctx.exception))

    def test_verify_jobs_db_with_empty_table_passes_and_snapshots(self) -> None:
        """When jobs.sqlite3 has the valid table with 0 rows, check passes cleanly."""
        self._init_valid_jobs_db()
        res = verify_workspace_integrity(self.r_root)
        self.assertTrue(res["passed"])
        self.assertEqual(res["job_count"], 0)
        self.assertEqual(res["errors"], [])

        snap_dir = self.root / "snapshots" / "empty_jobs_snap"
        snap = create_workspace_snapshot(self.r_root, snap_dir)
        self.assertTrue(snap["integrity"]["passed"])

    def test_verify_generation_runs_schema_id_vs_run_id_variants(self) -> None:
        """Verify dynamic schema handling for 'id' vs legacy 'run_id' vs both vs invalid in runs table."""
        self._init_valid_jobs_db()

        # Variant 1: Modern schema (column 'id')
        gen_db = self.g_root / "generation.sqlite3"
        conn = sqlite3.connect(gen_db)
        conn.execute("CREATE TABLE runs (id TEXT PRIMARY KEY, record TEXT NOT NULL)")
        rec1 = json.dumps({"id": "run_modern", "status": "pending", "workflow_hash": "w1"})
        conn.execute("INSERT INTO runs VALUES (?, ?)", ("run_modern", rec1))
        conn.commit()
        conn.close()

        res1 = verify_workspace_integrity(self.r_root, self.g_root)
        self.assertTrue(res1["passed"], f"Errors: {res1['errors']}")
        self.assertEqual(len(res1["generation_runs"]), 1)
        self.assertEqual(res1["generation_runs"][0]["id"], "run_modern")

        # Variant 2: Legacy schema (column 'run_id')
        gen_db.unlink()
        conn = sqlite3.connect(gen_db)
        conn.execute("CREATE TABLE runs (run_id TEXT PRIMARY KEY, record TEXT NOT NULL)")
        rec2 = json.dumps({"id": "run_legacy", "status": "queued", "workflow_hash": "w2"})
        conn.execute("INSERT INTO runs VALUES (?, ?)", ("run_legacy", rec2))
        conn.commit()
        conn.close()

        res2 = verify_workspace_integrity(self.r_root, self.g_root)
        self.assertTrue(res2["passed"], f"Errors: {res2['errors']}")
        self.assertEqual(len(res2["generation_runs"]), 1)
        self.assertEqual(res2["generation_runs"][0]["id"], "run_legacy")

        # Variant 3: Both 'id' and 'run_id' present
        gen_db.unlink()
        conn = sqlite3.connect(gen_db)
        conn.execute("CREATE TABLE runs (id TEXT, run_id TEXT, record TEXT NOT NULL)")
        rec3 = json.dumps({"id": "run_both", "status": "queued", "workflow_hash": "w3"})
        conn.execute("INSERT INTO runs VALUES (?, ?, ?)", ("run_both", "run_both", rec3))
        conn.commit()
        conn.close()

        res3 = verify_workspace_integrity(self.r_root, self.g_root)
        self.assertTrue(res3["passed"], f"Errors: {res3['errors']}")
        self.assertEqual(len(res3["generation_runs"]), 1)
        self.assertEqual(res3["generation_runs"][0]["id"], "run_both")

        # Variant 4: Neither 'id' nor 'run_id' present (invalid schema)
        gen_db.unlink()
        conn = sqlite3.connect(gen_db)
        conn.execute("CREATE TABLE runs (custom_key TEXT PRIMARY KEY, record TEXT NOT NULL)")
        rec4 = json.dumps({"id": "run_invalid", "status": "queued"})
        conn.execute("INSERT INTO runs VALUES (?, ?)", ("run_invalid", rec4))
        conn.commit()
        conn.close()

        res4 = verify_workspace_integrity(self.r_root, self.g_root)
        self.assertFalse(res4["passed"])
        self.assertTrue(any("no such column: id" in err for err in res4["errors"]))

    def test_verify_queue_sqlite3_empty_and_valid_records(self) -> None:
        """Verify queue.sqlite3 empty table resilience and invalid record detection."""
        self._init_valid_jobs_db()

        # Empty queue.sqlite3 with 0 tables passes
        queue_db = self.g_root / "queue.sqlite3"
        sqlite3.connect(queue_db).close()
        res_empty = verify_workspace_integrity(self.r_root, self.g_root)
        self.assertTrue(res_empty["passed"])
        self.assertEqual(res_empty["generation_task_count"], 0)

        # Valid tasks table
        conn = sqlite3.connect(queue_db)
        conn.execute("CREATE TABLE tasks (id TEXT PRIMARY KEY, record TEXT NOT NULL)")
        task_rec = json.dumps({"id": "task_1", "job_id": "j1", "status": "pending"})
        conn.execute("INSERT INTO tasks VALUES (?, ?)", ("task_1", task_rec))
        conn.commit()
        conn.close()

        res_valid = verify_workspace_integrity(self.r_root, self.g_root)
        self.assertTrue(res_valid["passed"])
        self.assertEqual(res_valid["generation_task_count"], 1)

        # Corrupted JSON record in queue.sqlite3
        conn = sqlite3.connect(queue_db)
        conn.execute("INSERT INTO tasks VALUES (?, ?)", ("task_bad", "{broken json"))
        conn.commit()
        conn.close()

        res_bad = verify_workspace_integrity(self.r_root, self.g_root)
        self.assertFalse(res_bad["passed"])
        self.assertTrue(any("Generation queue task task_bad: invalid JSON" in err for err in res_bad["errors"]))

    def test_verify_detects_corrupted_sqlite_files(self) -> None:
        """Verify that files with corrupted headers or truncated SQLite content fail closed."""
        # 1. Non-sqlite bytes in jobs.sqlite3
        (self.r_root / "jobs.sqlite3").write_bytes(b"NOT_A_VALID_SQLITE_DATABASE_DATA")
        res1 = verify_workspace_integrity(self.r_root)
        self.assertFalse(res1["passed"])
        self.assertTrue(any("file is not a database" in err for err in res1["errors"]))

        # 2. Corrupt generation.sqlite3
        self.r_root.joinpath("jobs.sqlite3").unlink()
        self._init_valid_jobs_db()
        (self.g_root / "generation.sqlite3").write_bytes(b"GARBAGE_HEADER_DATA_1234567890")
        res2 = verify_workspace_integrity(self.r_root, self.g_root)
        self.assertFalse(res2["passed"])
        self.assertTrue(any("file is not a database" in err for err in res2["errors"]))

    def test_verify_detects_completed_run_missing_output_or_sha_mismatch(self) -> None:
        """Completed runs in generation ledger must have their cached PNG and matching sha256."""
        self._init_valid_jobs_db()
        gen_db = self.g_root / "generation.sqlite3"
        conn = sqlite3.connect(gen_db)
        conn.execute("CREATE TABLE runs (id TEXT PRIMARY KEY, record TEXT NOT NULL)")

        # Record claims completed but no png exists
        rec1 = json.dumps({"id": "run_comp", "status": "completed", "output_sha256": "expected_sha"})
        conn.execute("INSERT INTO runs VALUES (?, ?)", ("run_comp", rec1))
        conn.commit()
        conn.close()

        res1 = verify_workspace_integrity(self.r_root, self.g_root)
        self.assertFalse(res1["passed"])
        self.assertTrue(any("missing cached output run_comp.png" in err for err in res1["errors"]))

        # Create png with mismatched sha256
        png_path = self.g_root / "run_comp.png"
        png_path.write_bytes(b"\x89PNG\r\n\x1a\nfake-png-content")

        res2 = verify_workspace_integrity(self.r_root, self.g_root)
        self.assertFalse(res2["passed"])
        self.assertTrue(any("cached output sha256 mismatch" in err for err in res2["errors"]))

        # Fix sha256
        correct_sha = hashlib.sha256(png_path.read_bytes()).hexdigest()
        conn = sqlite3.connect(gen_db)
        rec1_fixed = json.dumps({"id": "run_comp", "status": "completed", "output_sha256": correct_sha})
        conn.execute("UPDATE runs SET record = ? WHERE id = 'run_comp'", (rec1_fixed,))
        conn.commit()
        conn.close()

        res3 = verify_workspace_integrity(self.r_root, self.g_root)
        self.assertTrue(res3["passed"], f"Errors: {res3['errors']}")

    def test_verify_handles_locked_database_without_unhandled_crash(self) -> None:
        """When an SQLite database is locked by another connection, timeout fails gracefully with error."""
        self._init_valid_jobs_db()
        jobs_db = self.r_root / "jobs.sqlite3"

        # Hold exclusive lock in a separate connection
        lock_conn = sqlite3.connect(jobs_db)
        lock_conn.execute("BEGIN EXCLUSIVE")

        try:
            real_connect = sqlite3.connect
            with patch("sqlite3.connect", side_effect=lambda *args, **kwargs: real_connect(jobs_db, timeout=0.1)):
                res = verify_workspace_integrity(self.r_root)
                self.assertFalse(res["passed"])
                self.assertTrue(any("database is locked" in err for err in res["errors"]))
        finally:
            lock_conn.close()

    def test_snapshot_includes_and_restores_all_root_and_nested_sqlite3_ledgers(self) -> None:
        """Confirm create_workspace_snapshot captures all *.sqlite3 files and restore preserves them."""
        self._init_valid_jobs_db()

        # 1. Root ledgers in generation_runs
        conn1 = sqlite3.connect(self.g_root / "generation.sqlite3")
        conn1.execute("CREATE TABLE runs (id TEXT PRIMARY KEY, record TEXT NOT NULL)")
        conn1.commit(); conn1.close()

        conn2 = sqlite3.connect(self.g_root / "queue.sqlite3")
        conn2.execute("CREATE TABLE tasks (id TEXT PRIMARY KEY, record TEXT NOT NULL)")
        conn2.commit(); conn2.close()

        conn3 = sqlite3.connect(self.g_root / "audit_telemetry.sqlite3")
        conn3.execute("CREATE TABLE audit (timestamp TEXT, event TEXT)")
        conn3.commit(); conn3.close()

        # 2. Nested ledgers in generation_runs/runs/
        runs_dir = self.g_root / "runs"
        runs_dir.mkdir()

        conn4 = sqlite3.connect(runs_dir / "generation.sqlite3")
        conn4.execute("CREATE TABLE runs (id TEXT PRIMARY KEY, record TEXT NOT NULL)")
        conn4.commit(); conn4.close()

        conn5 = sqlite3.connect(runs_dir / "worker_node_b.sqlite3")
        conn5.execute("CREATE TABLE runs (run_id TEXT PRIMARY KEY, record TEXT NOT NULL)")
        conn5.commit(); conn5.close()

        # Snapshot
        snap_dir = self.root / "snapshots" / "multi_ledger_snap"
        snap = create_workspace_snapshot(self.r_root, snap_dir, generation_root=self.g_root)
        self.assertTrue(snap["integrity"]["passed"])

        # Check snapshot contents
        snap_gen = snap_dir / "generation_runs"
        root_sqlite_files = {p.name for p in snap_gen.glob("*.sqlite3")}
        self.assertIn("generation.sqlite3", root_sqlite_files)
        self.assertIn("queue.sqlite3", root_sqlite_files)
        self.assertIn("audit_telemetry.sqlite3", root_sqlite_files)

        nested_sqlite_files = {p.name for p in (snap_gen / "runs").glob("*.sqlite3")}
        self.assertIn("generation.sqlite3", nested_sqlite_files)
        self.assertIn("worker_node_b.sqlite3", nested_sqlite_files)

        # Restore into clean targets
        restored_r = self.root / "restored_r"
        restored_g = self.root / "restored_g"
        restore_res = restore_workspace_snapshot(snap_dir, restored_r, generation_root=restored_g)
        self.assertTrue(restore_res["integrity"]["passed"])
        self.assertEqual(restore_res["state_fingerprint"], snap["integrity"]["state_fingerprint"])

        # Verify all restored sqlite3 files exist and are queryable
        restored_root_files = {p.name for p in restored_g.glob("*.sqlite3")}
        self.assertEqual(restored_root_files, root_sqlite_files)

        restored_nested_files = {p.name for p in (restored_g / "runs").glob("*.sqlite3")}
        self.assertEqual(restored_nested_files, nested_sqlite_files)

    def test_restore_rejects_tampered_snapshot_manifest_and_fingerprint(self) -> None:
        """restore_workspace_snapshot must reject tampered snapshot files before touching target dirs."""
        self._init_valid_jobs_db()
        snap_dir = self.root / "snapshots" / "tamper_snap"
        snap = create_workspace_snapshot(self.r_root, snap_dir)

        # Tamper: corrupt snapshot jobs.sqlite3
        (snap_dir / "region_jobs" / "jobs.sqlite3").write_bytes(b"TAMPERED_BYTES")

        target_r = self.root / "target_r"
        with self.assertRaises(ValueError) as ctx:
            restore_workspace_snapshot(snap_dir, target_r)
        self.assertIn("failed pre-restore integrity verification", str(ctx.exception))
        # Ensure target directory was not created or modified
        self.assertFalse(target_r.exists())


class AdversarialRestorationRunnerROIInvariantTests(unittest.TestCase):
    """Stress tests for fidelis/engine/restoration_runner.py ROI processing and fallback invariants."""

    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory(prefix="adv_roi_")
        self.addCleanup(self.tmp_dir.cleanup)
        self.root = Path(self.tmp_dir.name)

        # Non-trivial high-contrast base image
        self.src_rgb = _make_test_rgb(16, 16, seed=42)
        self.base_4x = np.asarray(
            Image.fromarray(self.src_rgb).resize((64, 64), Image.Resampling.BICUBIC),
            dtype=np.uint8,
        )

        # Radically inverted candidate image
        self.cand_4x = (255 - self.base_4x).astype(np.uint8)
        Image.fromarray(self.cand_4x).save(self.root / "candidate.png")
        self.runner = create_restoration_runner("imported", imported_dir=self.root)

    def test_empty_rois_strictly_fall_back_to_bitwise_identical_base(self) -> None:
        """AGENTS.md: Unknown or low-confidence regions remain on precision base. Empty rois == 100% base."""
        res = self.runner.run(
            self.src_rgb,
            scale=4,
            rois=[],
            apply_texture_guard=True,
            case_id="candidate",
            use_sobel_heuristic=False,
        )
        self.assertTrue(np.array_equal(res.image, self.base_4x))
        # Test also with Sobel heuristic active
        res_sobel = self.runner.run(
            self.src_rgb,
            scale=4,
            rois=[],
            apply_texture_guard=True,
            case_id="candidate",
            use_sobel_heuristic=True,
        )
        self.assertTrue(np.array_equal(res_sobel.image, self.base_4x))

    def test_preservation_only_rois_strictly_fall_back_to_bitwise_identical_base(self) -> None:
        """When all ROIs are preserve policies (logos, hardware, identity), entire image remains 100% base."""
        preservation_rois = [
            {"id": "logo", "kind": "logo", "policy": "preserve", "rect": [4, 4, 16, 16]},
            {"id": "hw", "kind": "hardware", "policy": "preserve", "rect": [24, 24, 16, 16]},
            {"id": "txt", "kind": "text", "policy": "preserve", "rect": [44, 44, 12, 12]},
            {"id": "face", "kind": "identity", "policy": "preserve", "rect": [0, 40, 20, 20]},
        ]
        res = self.runner.run(
            self.src_rgb,
            scale=4,
            rois=preservation_rois,
            apply_texture_guard=True,
            case_id="candidate",
            use_sobel_heuristic=False,
        )
        # Not a single pixel should be replaced or synthesized
        self.assertTrue(np.array_equal(res.image, self.base_4x))
        self.assertEqual(res.drift_report["locked_pixel_mismatches"], 0)

    def test_unclassified_pixels_outside_partial_texture_roi_remain_bitwise_identical(self) -> None:
        """Pixels outside explicit texture-allowed ROIs must remain 100% bitwise identical to base."""
        tx_rect = [16, 16, 24, 24]
        texture_roi = [
            {"id": "fab", "kind": "fabric", "policy": "texture_allowed", "rect": tx_rect}
        ]
        res = self.runner.run(
            self.src_rgb,
            scale=4,
            rois=texture_roi,
            apply_texture_guard=True,
            case_id="candidate",
            use_sobel_heuristic=False,
        )
        x, y, w, h = tx_rect
        roi_mask = np.zeros((64, 64), dtype=bool)
        roi_mask[y : y + h, x : x + w] = True
        unclassified_mask = ~roi_mask

        # Outside: exactly equal to base
        self.assertTrue(np.array_equal(res.image[unclassified_mask], self.base_4x[unclassified_mask]))
        # Inside: candidate was blended in and differs from base
        self.assertFalse(np.array_equal(res.image[roi_mask], self.base_4x[roi_mask]))

    def test_roi_negative_coordinates_clamped_and_unclassified_pixels_preserved(self) -> None:
        """ROIs with negative coordinates or out-of-bounds coords are clamped cleanly without out-of-bound errors."""
        # Partially negative ROI: [-10, -10, 24, 24] -> clamps to [0, 0, 24, 24]
        neg_roi = [
            {"id": "neg_box", "kind": "fabric", "policy": "texture_allowed", "rect": [-10, -10, 24, 24]}
        ]
        res = self.runner.run(
            self.src_rgb,
            scale=4,
            rois=neg_roi,
            apply_texture_guard=True,
            case_id="candidate",
            use_sobel_heuristic=False,
        )
        self.assertEqual(res.image.shape, (64, 64, 3))
        # Pixels outside the clamped region [0:24, 0:24] remain strictly identical to base
        unclassified = np.ones((64, 64), dtype=bool)
        unclassified[0:24, 0:24] = False
        self.assertTrue(np.array_equal(res.image[unclassified], self.base_4x[unclassified]))

        # Completely negative off-canvas preserve ROI leaves entire image on base
        off_canvas = [
            {"id": "far_neg", "kind": "hardware", "policy": "preserve", "rect": [-200, -200, 20, 20]}
        ]
        res_off = self.runner.run(
            self.src_rgb,
            scale=4,
            rois=off_canvas,
            apply_texture_guard=True,
            case_id="candidate",
            use_sobel_heuristic=False,
        )
        self.assertTrue(np.array_equal(res_off.image, self.base_4x))

    def test_roi_negative_and_zero_dimensions_normalization(self) -> None:
        """Negative and zero dimensions normalize to minimum positive extent (1px) without crash."""
        rois = [
            {"id": "neg_dims", "kind": "fabric", "policy": "texture_allowed", "rect": [10, 10, -5, -8]},
            {"id": "zero_dims", "kind": "hardware", "policy": "preserve", "rect": [30, 30, 0, 0]},
        ]
        res = self.runner.run(
            self.src_rgb,
            scale=4,
            rois=rois,
            apply_texture_guard=True,
            case_id="candidate",
            use_sobel_heuristic=False,
        )
        self.assertEqual(res.image.shape, (64, 64, 3))
        # Unclassified pixels outside [10:11, 10:11] must equal base
        unclass = np.ones((64, 64), dtype=bool)
        unclass[10:11, 10:11] = False
        self.assertTrue(np.array_equal(res.image[unclass], self.base_4x[unclass]))

    def test_full_image_rois_preservation_texture_and_overrides(self) -> None:
        """Full-image ROIs under various policy and override combinations."""
        full_rect = [0, 0, 64, 64]

        # 1. Full-image preserve -> 100% bitwise equal to base
        r_p = [{"id": "f_p", "kind": "hardware", "policy": "preserve", "rect": full_rect}]
        res_p = self.runner.run(self.src_rgb, scale=4, rois=r_p, case_id="candidate")
        self.assertTrue(np.array_equal(res_p.image, self.base_4x))

        # 2. Full-image texture_allowed -> candidate blended in
        r_t = [{"id": "f_t", "kind": "fabric", "policy": "texture_allowed", "rect": full_rect}]
        res_t = self.runner.run(self.src_rgb, scale=4, rois=r_t, case_id="candidate")
        self.assertFalse(np.array_equal(res_t.image, self.base_4x))

        # 3. Full-image texture_allowed with explicit lock override -> 100% base (lock wins)
        r_lock = [{"id": "f_l", "kind": "fabric", "policy": "texture_allowed", "override": "lock", "rect": full_rect}]
        res_lock = self.runner.run(self.src_rgb, scale=4, rois=r_lock, case_id="candidate")
        self.assertTrue(np.array_equal(res_lock.image, self.base_4x))

        # 4. Full-image preserve with explicit unlock override -> candidate blended in (unlock wins)
        r_unlock = [{"id": "f_u", "kind": "hardware", "policy": "preserve", "override": "unlock", "rect": full_rect}]
        res_unlock = self.runner.run(self.src_rgb, scale=4, rois=r_unlock, case_id="candidate")
        self.assertFalse(np.array_equal(res_unlock.image, self.base_4x))

    def test_overlapping_preserve_and_texture_rois_explicit_protection_wins(self) -> None:
        """AGENTS.md: Explicit protection wins over semantic texture masks."""
        rois = [
            {"id": "bg_fabric", "kind": "fabric", "policy": "texture_allowed", "rect": [0, 0, 64, 64]},
            {"id": "metal_hardware", "kind": "hardware", "policy": "preserve", "rect": [16, 16, 32, 32]},
        ]
        res = self.runner.run(
            self.src_rgb,
            scale=4,
            rois=rois,
            case_id="candidate",
            use_sobel_heuristic=False,
        )
        # Inside hardware [16:48, 16:48]: MUST equal base_4x byte-for-byte
        np.testing.assert_array_equal(res.image[16:48, 16:48], self.base_4x[16:48, 16:48])
        # Outside hardware: candidate blended in
        bg_mask = np.ones((64, 64), dtype=bool)
        bg_mask[16:48, 16:48] = False
        self.assertFalse(np.array_equal(res.image[bg_mask], self.base_4x[bg_mask]))
        self.assertEqual(res.drift_report["locked_pixel_mismatches"], 0)

    def test_comfy_workflow_vs_checkpoint_hash_separation(self) -> None:
        """Graph digest does not attest to model checkpoint bytes; workflow_sha256 != weights_sha256."""
        bundle_no_ckpt = {"schema_version": 1, "family": "flux", "workflow": {"node1": {"class": "KSampler"}}}

        class _MockComfy:
            address = "http://127.0.0.1:8188"
            def default_cli_run_id(self, canvas, b, addr): return "r-1"
            def run(self, canvas, b, *, run_id=None, deadline_seconds=300):
                return canvas, {"id": run_id, "workflow_sha256": "wf_123"}

        backend = ComfyRestorationBackend(bundle=bundle_no_ckpt, comfy_backend=_MockComfy())
        self.assertNotEqual(backend.workflow_sha256, backend.weights_sha256)
        self.assertEqual(backend.weights_sha256, "unavailable_unverified")

        # When checkpoint_sha256 is provided
        bundle_with_ckpt = {
            "schema_version": 1,
            "family": "flux",
            "checkpoint_sha256": "deadbeef" * 8,
            "workflow": {"node1": {"class": "KSampler"}},
        }
        backend_ckpt = ComfyRestorationBackend(bundle=bundle_with_ckpt, comfy_backend=_MockComfy())
        self.assertEqual(backend_ckpt.weights_sha256, "deadbeef" * 8)
        self.assertNotEqual(backend_ckpt.workflow_sha256, backend_ckpt.weights_sha256)

    def test_restoration_runner_input_validation_and_fail_closed(self) -> None:
        """Validate that malformed inputs to RestorationRunner fail closed with appropriate errors."""
        # 1. Invalid dtype (float instead of uint8)
        with self.assertRaises(ValueError):
            self.runner.run(self.src_rgb.astype(np.float32), scale=4)

        # 2. Invalid shape (2D or 4-channel)
        with self.assertRaises(ValueError):
            self.runner.run(self.src_rgb[:, :, 0], scale=4)
        with self.assertRaises(ValueError):
            self.runner.run(np.zeros((16, 16, 4), dtype=np.uint8), scale=4)

        # 3. Invalid scale (< 1)
        with self.assertRaises(ValueError) as ctx:
            self.runner.run(self.src_rgb, scale=0)
        self.assertIn("scale must be >= 1", str(ctx.exception))

        # 4. Invalid target_size
        with self.assertRaises(DimensionMismatchError):
            self.runner.run(self.src_rgb, scale=4, target_size=(0, 64))

        # 5. Invalid roi_space (when rois provided)
        with self.assertRaises(ValueError) as ctx:
            self.runner.run(
                self.src_rgb,
                scale=4,
                case_id="candidate",
                rois=[{"id": "1", "kind": "fabric", "rect": [0, 0, 10, 10]}],
                roi_space="nonexistent_space",
            )
        self.assertIn("Unsupported roi_space", str(ctx.exception))

        # 6. Invalid ROI entry (not a mapping) raises TypeError
        with self.assertRaises(TypeError):
            self.runner.run(self.src_rgb, scale=4, case_id="candidate", rois=["not_a_mapping"])

        # 7. Invalid kind in ROI
        with self.assertRaises(ValueError) as ctx:
            self.runner.run(self.src_rgb, scale=4, case_id="candidate", rois=[{"id": "1", "kind": "alien", "rect": [0, 0, 10, 10]}])
        self.assertIn("invalid kind 'alien'", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
