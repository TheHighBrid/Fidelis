"""Regression tests for F14 resumable, bounded batch processing."""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import threading
import time
import tempfile
import unittest

import numpy as np
from PIL import Image

from fidelis.studio.batch import BatchItemContext, BatchRunner
from fidelis.studio.comfy import SubmissionUnknown
from fidelis.studio.store import BudgetExceeded, sha256


class BatchRunnerTests(unittest.TestCase):
    def _make_images(self, root: Path, names: tuple[str, ...]) -> list[Path]:
        in_dir = root / "inputs"
        in_dir.mkdir(parents=True, exist_ok=True)
        paths = []
        for idx, name in enumerate(names):
            arr = np.full((12, 16, 3), 40 + idx * 35, dtype=np.uint8)
            p = in_dir / name
            Image.fromarray(arr, "RGB").save(p)
            paths.append(p)
        return paths

    def test_crash_recovery_prevents_duplicate_paid_work_and_reconciles_safely(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inputs = self._make_images(root, ("a.png", "b.png", "c.png", "d.png"))
            out_dir = root / "outputs"
            batch_dir = root / "batch"

            entries = [
                {
                    "source_path": str(p),
                    "output_path": str(out_dir / p.name),
                    "recipe": {"profile": "luxury_apparel", "step": idx},
                    "estimated_cost_usd": 0.25,
                }
                for idx, p in enumerate(inputs)
            ]

            with BatchRunner(batch_dir, max_workers=2, max_retries=2) as runner:
                enq = runner.enqueue(entries)
                self.assertEqual(enq, {"enqueued": 4, "skipped_existing": 0})
                # Re-enqueueing identical recipes is idempotent.
                self.assertEqual(runner.enqueue(entries), {"enqueued": 0, "skipped_existing": 4})

                calls: list[str] = []

                def first_pass(ctx: BatchItemContext) -> dict:
                    calls.append(ctx.item["source_path"])
                    name = Path(ctx.item["source_path"]).name
                    if name == "a.png":
                        ctx.mark_paid_submitted(0.25)
                        ctx.temp_output_path.write_bytes(Path(ctx.item["source_path"]).read_bytes())
                        return {"actual_cost_usd": 0.25}
                    if name == "b.png":
                        # Paid remote request became uncertain (timeout / 502).
                        ctx.mark_paid_submitted(0.25)
                        raise SubmissionUnknown("Timeout waiting on remote worker")
                    if name == "c.png":
                        # Pre-submit failure before paid work.
                        raise RuntimeError("Local disk cache temporarily busy")
                    ctx.temp_output_path.write_bytes(Path(ctx.item["source_path"]).read_bytes())
                    return {"actual_cost_usd": 0.0}

                st1 = runner.run(first_pass, retry_failed=False)
                self.assertEqual(st1["counts"]["completed"], 2)  # a.png, d.png
                self.assertEqual(st1["counts"]["needs_review"], 1)  # b.png
                self.assertEqual(st1["counts"]["failed"], 1)  # c.png

            # Simulate an ungraceful process crash leaving item 'd.png' in status='running'
            # WITHOUT paid_work_committed, and confirm startup recovery marks it 'interrupted'.
            conn = sqlite3.connect(batch_dir / "batch.sqlite3")
            with conn:
                rows = [json.loads(r[0]) for r in conn.execute("SELECT record FROM items").fetchall()]
                for rec in rows:
                    if Path(rec["source_path"]).name == "d.png":
                        rec["status"] = "running"
                        rec["paid_work_committed"] = False
                        conn.execute(
                            "UPDATE items SET record=? WHERE item_id=?",
                            (json.dumps(rec), rec["item_id"]),
                        )
            conn.close()
            # Also plant an orphan temp artifact that must be purged on startup.
            (batch_dir / ".tmp" / "stale.part").write_bytes(b"partial")

            resumed_calls: list[str] = []
            reconciled_ids: list[str] = []

            def second_pass(ctx: BatchItemContext) -> dict:
                resumed_calls.append(Path(ctx.item["source_path"]).name)
                ctx.temp_output_path.write_bytes(Path(ctx.item["source_path"]).read_bytes())
                return {"actual_cost_usd": 0.25}

            def reconcile(item: dict) -> dict:
                reconciled_ids.append(item["run_id"])
                out = Path(item["output_path"])
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(Path(item["source_path"]).read_bytes())
                return {"status": "completed", "output_path": str(out), "actual_cost_usd": 0.25}

            with BatchRunner(batch_dir, max_workers=2, max_retries=2) as runner2:
                self.assertFalse((batch_dir / ".tmp" / "stale.part").exists())
                # Wait: completed item a.png must NOT be re-executed; needs_review b.png MUST NOT hit second_pass!
                st2 = runner2.run(second_pass, retry_failed=True, reconcile_fn=reconcile)
                self.assertEqual(sorted(resumed_calls), ["c.png", "d.png"])
                self.assertNotIn("a.png", resumed_calls)
                self.assertNotIn("b.png", resumed_calls)
                self.assertEqual(len(reconciled_ids), 1)
                self.assertEqual(st2["counts"]["completed"], 4)
                self.assertEqual(st2["total_retries"], 1)

    def test_bounded_concurrency_retry_cap_and_budgets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inputs = self._make_images(root, ("1.png", "2.png", "3.png", "4.png", "5.png"))
            batch_dir = root / "batch"
            out_dir = root / "out"

            entries = [
                {
                    "source_path": str(p),
                    "output_path": str(out_dir / p.name),
                    "recipe": {"idx": idx},
                    "estimated_cost_usd": 0.20,
                }
                for idx, p in enumerate(inputs)
            ]

            active = 0
            max_seen = 0
            lock = threading.Lock()

            def bounded_worker(ctx: BatchItemContext) -> dict:
                nonlocal active, max_seen
                with lock:
                    active += 1
                    max_seen = max(max_seen, active)
                try:
                    time.sleep(0.03)
                    ctx.temp_output_path.write_bytes(Path(ctx.item["source_path"]).read_bytes())
                    return {"actual_cost_usd": 0.20}
                finally:
                    with lock:
                        active -= 1

            # Enforce cost budget 0.45 USD -> only 2 items fit cleanly (0.40 <= 0.45), 3 fail with BudgetExceeded.
            with BatchRunner(batch_dir, max_workers=2, cost_budget_usd=0.45) as runner:
                runner.enqueue(entries)
                summary = runner.run(bounded_worker)
                self.assertLessEqual(max_seen, 2)
                self.assertEqual(summary["counts"]["completed"], 2)
                self.assertEqual(summary["counts"]["failed"], 3)
                failed = [x for x in summary["items"] if x["status"] == "failed"]
                self.assertTrue(all(x["error_type"] == "BudgetExceeded" for x in failed))

            # Verify strict single-owner flock blocks concurrent BatchRunner on same directory.
            holder = BatchRunner(batch_dir, max_workers=1)
            try:
                with self.assertRaises(RuntimeError):
                    BatchRunner(batch_dir, max_workers=1)
            finally:
                holder.close()

            # Verify max_retries stops repeated local failures and keeps attempt_history visible.
            fail_batch = root / "fail_batch"
            with BatchRunner(fail_batch, max_workers=1, max_retries=1) as fr:
                fr.enqueue([entries[0]])

                def always_fail(_ctx: BatchItemContext) -> dict:
                    raise ValueError("synthetic encode failure")

                fr.run(always_fail, retry_failed=True)
                s1 = fr.run(always_fail, retry_failed=True)  # 1 retry allowed -> total 2 attempts
                s2 = fr.run(always_fail, retry_failed=True)  # capped at retry_count == 1
                self.assertEqual(s1["items"][0]["attempts"], 2)
                self.assertEqual(s2["items"][0]["attempts"], 2)
                self.assertEqual(len(s2["items"][0]["attempt_history"]), 2)

            # Verify disk budget allows 1 output + recipe (~800 B) and blocks remaining items cleanly.
            disk_batch = root / "disk_batch"
            disk_out = root / "disk_out"
            disk_entries = [
                {
                    "source_path": str(p),
                    "output_path": str(disk_out / p.name),
                    "recipe": {"idx": idx, "lane": "disk_cap"},
                }
                for idx, p in enumerate(inputs[:3])
            ]
            tiny_limit = inputs[0].stat().st_size + 1000
            with BatchRunner(disk_batch, max_workers=1, disk_budget_bytes=tiny_limit) as dr:
                dr.enqueue(disk_entries)
                ds = dr.run(bounded_worker)
                self.assertEqual(ds["counts"]["completed"], 1)
                self.assertEqual(ds["counts"]["failed"], 2)
                self.assertLessEqual(ds["disk_used_bytes"], tiny_limit)

    def test_tampered_source_and_missing_output_detected_without_silent_loss(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inputs = self._make_images(root, ("p1.png",))
            out_dir = root / "out"
            batch_dir = root / "batch"

            with BatchRunner(batch_dir) as runner:
                runner.enqueue(
                    [
                        {
                            "source_path": str(inputs[0]),
                            "output_path": str(out_dir / "p1.png"),
                            "recipe": {"k": 1},
                        }
                    ]
                )
                # Mutate source file after enqueue -> run must fail closed!
                inputs[0].write_bytes(b"tampered")
                st = runner.run(lambda ctx: {"output_path": str(ctx.temp_output_path)})
                self.assertEqual(st["counts"]["failed"], 1)
                self.assertIn("altered since enqueue", st["items"][0]["error"])

            # Delete completed output externally -> next run surfaces integrity mismatch.
            inputs2 = self._make_images(root / "second", ("p2.png",))
            batch2 = root / "batch2"
            with BatchRunner(batch2) as r2:
                r2.enqueue(
                    [
                        {
                            "source_path": str(inputs2[0]),
                            "output_path": str(out_dir / "p2.png"),
                            "recipe": {"k": 2},
                        }
                    ]
                )
                r2.run(
                    lambda ctx: (
                        ctx.temp_output_path.write_bytes(Path(ctx.item["source_path"]).read_bytes()),
                        {"actual_cost_usd": 0.0},
                    )[1]
                )
                (out_dir / "p2.png").unlink()
                st_missing = r2.run(lambda ctx: {"actual_cost_usd": 0.0})
                self.assertEqual(st_missing["counts"]["failed"], 1)
                self.assertEqual(st_missing["items"][0]["error_type"], "OutputIntegrityMismatch")

    def test_cli_batch_run_enqueue_run_status_and_idempotent_resume(self) -> None:
        script = Path(__file__).resolve().parents[1] / "scripts/batch-run.py"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._make_images(root, ("img1.png", "img2.png"))
            batch_dir = root / "batch"
            out_dir = root / "out"

            subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "enqueue",
                    "--batch-dir",
                    str(batch_dir),
                    "--input-dir",
                    str(root / "inputs"),
                    "--output-dir",
                    str(out_dir),
                    "--handler",
                    "deterministic_bicubic",
                    "--scale",
                    "2",
                    "--max-workers",
                    "2",
                ],
                check=True,
                capture_output=True,
                text=True,
            )

            run1 = subprocess.run(
                [sys.executable, str(script), "run", "--batch-dir", str(batch_dir)],
                check=True,
                capture_output=True,
                text=True,
            )
            p1 = json.loads(run1.stdout)
            self.assertEqual(p1["counts"]["completed"], 2)
            self.assertEqual(len(list(out_dir.glob("*.png"))), 2)
            self.assertEqual(len(list(out_dir.glob("*.recipe.json"))), 2)

            with Image.open(out_dir / "img1.png") as im:
                self.assertEqual(im.size, (32, 24))
            recipe = json.loads((out_dir / "img1.png.recipe.json").read_text(encoding="utf-8"))
            self.assertEqual(recipe["provenance"], "unsigned_execution_record")
            self.assertEqual(recipe["attempt"], 1)

            # Second run skips completed items with zero duplicate attempts.
            run2 = subprocess.run(
                [sys.executable, str(script), "run", "--batch-dir", str(batch_dir)],
                check=True,
                capture_output=True,
                text=True,
            )
            p2 = json.loads(run2.stdout)
            self.assertTrue(all(item["attempts"] == 1 for item in p2["items"]))

            # Read-only status works cleanly while runner isn't running.
            st = subprocess.run(
                [sys.executable, str(script), "status", "--batch-dir", str(batch_dir)],
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertEqual(json.loads(st.stdout)["counts"]["completed"], 2)

    def test_persisted_budgets_and_packshot_extension_preserved_across_cli_reopen(self) -> None:
        script = Path(__file__).resolve().parents[1] / "scripts/batch-run.py"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            in_dir = root / "inputs"
            in_dir.mkdir(parents=True, exist_ok=True)
            jpg_path = in_dir / "photo.jpg"
            arr = np.full((12, 16, 3), 90, dtype=np.uint8)
            Image.fromarray(arr, "RGB").save(jpg_path, format="JPEG")

            batch_dir = root / "batch"
            out_dir = root / "out"

            enq = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "enqueue",
                    "--batch-dir",
                    str(batch_dir),
                    "--input-dir",
                    str(in_dir),
                    "--output-dir",
                    str(out_dir),
                    "--handler",
                    "packshot_verify",
                    "--max-workers",
                    "1",
                    "--max-items",
                    "10",
                    "--disk-budget-mib",
                    "64",
                    "--max-retries",
                    "4",
                    "--cost-budget-usd",
                    "0.10",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            enq_payload = json.loads(enq.stdout)["status"]
            self.assertEqual(enq_payload["disk_budget_bytes"], 64 * 1024 * 1024)
            self.assertEqual(enq_payload["cost_budget_usd"], 0.10)
            self.assertEqual(enq_payload["max_workers"], 1)
            self.assertEqual(enq_payload["max_items"], 10)
            self.assertEqual(enq_payload["max_retries"], 4)

            # Reopen via 'run' without budget flags: persisted budgets must remain in force.
            run_res = subprocess.run(
                [sys.executable, str(script), "run", "--batch-dir", str(batch_dir)],
                check=True,
                capture_output=True,
                text=True,
            )
            run_payload = json.loads(run_res.stdout)
            self.assertEqual(run_payload["counts"]["completed"], 1)
            self.assertEqual(run_payload["disk_budget_bytes"], 64 * 1024 * 1024)
            self.assertEqual(run_payload["cost_budget_usd"], 0.10)
            self.assertEqual(run_payload["max_workers"], 1)
            self.assertEqual(run_payload["max_items"], 10)
            self.assertEqual(run_payload["max_retries"], 4)

            # packshot_verify must keep .jpg extension rather than writing JPEG bytes as .png.
            self.assertTrue((out_dir / "photo.jpg").is_file())
            self.assertFalse((out_dir / "photo.png").exists())
            self.assertEqual((out_dir / "photo.jpg").read_bytes(), jpg_path.read_bytes())

            # Read-only status also reports persisted budgets.
            st_res = subprocess.run(
                [sys.executable, str(script), "status", "--batch-dir", str(batch_dir)],
                check=True,
                capture_output=True,
                text=True,
            )
            st_payload = json.loads(st_res.stdout)
            self.assertEqual(st_payload["disk_budget_bytes"], 64 * 1024 * 1024)
            self.assertEqual(st_payload["cost_budget_usd"], 0.10)

    def test_paid_reservation_enforces_spend_cap_and_preserves_reserved_cost(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inputs = self._make_images(root, ("first.png", "second.png"))
            batch_dir = root / "batch"
            out_dir = root / "out"

            entries = [
                {
                    "source_path": str(inputs[0]),
                    "output_path": str(out_dir / "first.png"),
                    "recipe": {"idx": 0},
                    "estimated_cost_usd": 0.05,
                },
                {
                    "source_path": str(inputs[1]),
                    "output_path": str(out_dir / "second.png"),
                    "recipe": {"idx": 1},
                    "estimated_cost_usd": 0.05,
                },
            ]
            remote_submissions: list[str] = []

            def worker(ctx: BatchItemContext) -> dict:
                name = Path(ctx.item["source_path"]).name
                if name == "first.png":
                    # Reserve 0.12 USD (< 0.15 cap) and omit actual_cost_usd from return dict.
                    ctx.mark_paid_submitted(0.12)
                    remote_submissions.append(name)
                    ctx.temp_output_path.write_bytes(Path(ctx.item["source_path"]).read_bytes())
                    return {}
                # Second item was estimated at 0.05, but runtime quote is 0.10 -> 0.12 + 0.10 > 0.15 cap!
                ctx.mark_paid_submitted(0.10)
                remote_submissions.append(name)
                ctx.temp_output_path.write_bytes(Path(ctx.item["source_path"]).read_bytes())
                return {}

            with BatchRunner(batch_dir, max_workers=1, cost_budget_usd=0.15) as runner:
                runner.enqueue(entries)
                summary = runner.run(worker)

            self.assertEqual(remote_submissions, ["first.png"])
            self.assertEqual(summary["counts"]["completed"], 1)
            self.assertEqual(summary["counts"]["failed"], 1)
            self.assertEqual(summary["counts"]["needs_review"], 0)
            self.assertAlmostEqual(summary["total_cost_usd"], 0.12, places=6)
            second_item = next(x for x in summary["items"] if x["output_path"].endswith("second.png"))
            self.assertFalse(second_item["paid_work_committed"])
            self.assertEqual(second_item["error_type"], "BudgetExceeded")

    def test_cross_item_source_output_collision_and_external_reconcile_publish(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inputs = self._make_images(root, ("a.png", "b.png"))
            batch_dir = root / "batch"
            out_dir = root / "out"

            with BatchRunner(batch_dir, max_workers=1) as runner:
                # Reject A -> B and B -> C within a single enqueue call.
                with self.assertRaises(ValueError):
                    runner.enqueue(
                        [
                            {
                                "source_path": str(inputs[0]),
                                "output_path": str(inputs[1]),
                                "recipe": {"step": 1},
                            },
                            {
                                "source_path": str(inputs[1]),
                                "output_path": str(out_dir / "c.png"),
                                "recipe": {"step": 2},
                            },
                        ]
                    )

                # Enqueue A -> out/a.png, then reject out/a.png -> out/b.png on a subsequent enqueue.
                runner.enqueue(
                    [
                        {
                            "source_path": str(inputs[0]),
                            "output_path": str(out_dir / "a.png"),
                            "recipe": {"step": 1},
                            "estimated_cost_usd": 0.10,
                        }
                    ]
                )
                out_dir.mkdir(parents=True, exist_ok=True)
                (out_dir / "a.png").write_bytes(inputs[0].read_bytes())
                with self.assertRaises(ValueError):
                    runner.enqueue(
                        [
                            {
                                "source_path": str(out_dir / "a.png"),
                                "output_path": str(out_dir / "b.png"),
                                "recipe": {"step": 2},
                            }
                        ]
                    )
                (out_dir / "a.png").unlink()

                # Trigger needs_review on A, then reconcile from a separate backend cache file.
                def interrupt_worker(ctx: BatchItemContext) -> dict:
                    ctx.mark_paid_submitted(0.10)
                    raise SubmissionUnknown("connection reset after submit")

                s1 = runner.run(interrupt_worker)
                self.assertEqual(s1["counts"]["needs_review"], 1)

                cache_file = root / "cache" / "recovered_run.png"
                cache_file.parent.mkdir(parents=True, exist_ok=True)
                cache_file.write_bytes(inputs[0].read_bytes())

                s2 = runner.run(
                    lambda _ctx: {},
                    reconcile_fn=lambda _item: {
                        "status": "completed",
                        "output_path": str(cache_file),
                        "actual_cost_usd": 0.10,
                    },
                )
                self.assertEqual(s2["counts"]["completed"], 1)
                self.assertTrue((out_dir / "a.png").is_file())
                self.assertTrue((out_dir / "a.png.recipe.json").is_file())
                self.assertEqual(sha256(out_dir / "a.png"), sha256(cache_file))

                # Subsequent run must pass _verify_completed_integrity() cleanly.
                s3 = runner.run(lambda _ctx: {})
                self.assertEqual(s3["counts"]["completed"], 1)
                self.assertEqual(s3["counts"]["failed"], 0)


if __name__ == "__main__":
    unittest.main()
