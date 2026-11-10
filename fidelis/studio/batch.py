"""Resumable, bounded batch processing with durable per-item recipes and paid-work guards.

Each batch item receives a deterministic recipe hash and persisted run identity
before execution. Process crashes recover uncommitted work cleanly, while any item
that reached a committed remote/paid submission boundary enters ``needs_review`` and
cannot automatically trigger duplicate paid execution on resume or retry.
"""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor, wait
from contextlib import contextmanager
from dataclasses import dataclass
import fcntl
import json
import math
import os
from pathlib import Path
import sqlite3
import threading
import time
from typing import Any, Callable, Optional
import uuid

from fidelis.studio.comfy import SubmissionUnknown, canonical_hash
from fidelis.studio.store import BudgetExceeded, sha256

VALID_STATUSES = frozenset(
    {"pending", "running", "interrupted", "completed", "failed", "needs_review"}
)


@dataclass
class BatchItemContext:
    """Execution handle passed to a single-item worker callback."""

    item: dict[str, Any]
    temp_output_path: Path
    _mark_paid: Callable[[Optional[float]], None]

    def mark_paid_submitted(self, reserved_cost_usd: Optional[float] = None) -> None:
        """Persist commit boundary before invoking a paid or remote submission."""
        self._mark_paid(reserved_cost_usd)


class BatchRunner:
    """Single-owner SQLite-backed batch coordinator with bounded concurrency & budgets."""

    SCHEMA_VERSION = 1

    def __init__(
        self,
        batch_dir: str | Path,
        *,
        max_workers: int = 2,
        max_items: int = 5000,
        disk_budget_bytes: int = 2 * 1024**3,
        max_retries: int = 2,
        cost_budget_usd: Optional[float] = None,
        read_only: bool = False,
    ) -> None:
        if type(max_workers) is not int or not 1 <= max_workers <= 4:
            raise ValueError("max_workers must be an integer in [1, 4]")
        if type(max_items) is not int or not 1 <= max_items <= 10_000:
            raise ValueError("max_items must be an integer in [1, 10000]")
        if type(disk_budget_bytes) is not int or disk_budget_bytes <= 0:
            raise ValueError("disk_budget_bytes must be a positive integer")
        if type(max_retries) is not int or not 0 <= max_retries <= 10:
            raise ValueError("max_retries must be an integer in [0, 10]")
        if cost_budget_usd is not None and (
            not isinstance(cost_budget_usd, (int, float))
            or isinstance(cost_budget_usd, bool)
            or not math.isfinite(cost_budget_usd)
            or cost_budget_usd < 0
        ):
            raise ValueError("cost_budget_usd must be finite and >= 0")

        self.root = Path(batch_dir)
        self.db_path = self.root / "batch.sqlite3"
        self.tmp_dir = self.root / ".tmp"
        self.max_workers = max_workers
        self.max_items = max_items
        self.disk_budget_bytes = disk_budget_bytes
        self.max_retries = max_retries
        self.cost_budget_usd = float(cost_budget_usd) if cost_budget_usd is not None else None
        self.read_only = read_only
        self._lock = threading.RLock()
        self._owner = None
        self._closed = False

        if read_only:
            if not self.db_path.is_file():
                raise FileNotFoundError(f"Batch database not found: {self.db_path}")
            return

        self.root.mkdir(parents=True, exist_ok=True)
        self.tmp_dir.mkdir(parents=True, exist_ok=True)
        self._owner = (self.root / "batch.lock").open("a")
        try:
            fcntl.flock(self._owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            self._owner.close()
            self._owner = None
            raise RuntimeError("Another batch runner already owns this batch directory") from exc

        try:
            self._init_and_recover()
        except BaseException:
            self.close()
            raise

    def __enter__(self) -> "BatchRunner":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def close(self) -> None:
        if self._owner is not None:
            try:
                fcntl.flock(self._owner, fcntl.LOCK_UN)
            finally:
                self._owner.close()
                self._owner = None
        self._closed = True

    @contextmanager
    def _db(self):
        if self._closed:
            raise RuntimeError("BatchRunner is closed")
        conn = sqlite3.connect(self.db_path, timeout=5)
        try:
            if self.read_only:
                yield conn
            else:
                with conn:
                    yield conn
        finally:
            conn.close()

    def _init_and_recover(self) -> None:
        # Remove orphaned staging files from prior killed runs under single-owner lock.
        for orphan in self.tmp_dir.iterdir():
            if orphan.is_file():
                orphan.unlink(missing_ok=True)

        with self._db() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS items ("
                "idx INTEGER NOT NULL, "
                "item_id TEXT PRIMARY KEY, "
                "recipe_hash TEXT NOT NULL, "
                "record TEXT NOT NULL)"
            )
            rows = db.execute("SELECT record FROM items ORDER BY idx").fetchall()
            for (raw,) in rows:
                item = json.loads(raw)
                if item["status"] == "running":
                    if item.get("paid_work_committed"):
                        item["status"] = "needs_review"
                        item["error_type"] = "InterruptedCommittedSubmission"
                        item["error"] = (
                            "Process interrupted after committed/paid step; inspect or reconcile existing run_id before retrying"
                        )
                    else:
                        item["status"] = "interrupted"
                        item["error_type"] = "ProcessInterrupted"
                        item["error"] = "Process interrupted before submission commit; safe to resume"
                    item["updated_at_unix"] = time.time()
                    db.execute(
                        "UPDATE items SET record=? WHERE item_id=?",
                        (json.dumps(item, allow_nan=False), item["item_id"]),
                    )

    @staticmethod
    def _save_item(db: sqlite3.Connection, item: dict[str, Any]) -> None:
        item["updated_at_unix"] = time.time()
        db.execute(
            "UPDATE items SET record=? WHERE item_id=?",
            (json.dumps(item, allow_nan=False), item["item_id"]),
        )

    def _all_items(self, db: sqlite3.Connection) -> list[dict[str, Any]]:
        rows = db.execute("SELECT record FROM items ORDER BY idx").fetchall()
        return [json.loads(r[0]) for r in rows]

    def enqueue(self, entries: list[dict[str, Any]]) -> dict[str, Any]:
        """Validate and persist batch items with immutable source/recipe identities."""
        if self.read_only:
            raise RuntimeError("Cannot enqueue on a read-only BatchRunner")
        if not isinstance(entries, list) or not entries:
            raise ValueError("entries must be a non-empty list")

        enqueued = 0
        skipped_existing = 0
        with self._lock, self._db() as db:
            existing = self._all_items(db)
            if len(existing) + len(entries) > self.max_items:
                raise BudgetExceeded(
                    f"Batch item cap ({self.max_items}) exceeded: {len(existing)} + {len(entries)}"
                )
            by_recipe_hash = {item["recipe_hash"]: item for item in existing}
            by_output_path = {str(Path(item["output_path"]).resolve()): item for item in existing}
            next_idx = max((item["idx"] for item in existing), default=-1) + 1

            for entry in entries:
                src = Path(entry["source_path"]).resolve()
                dst = Path(entry["output_path"]).resolve()
                if not src.is_file():
                    raise FileNotFoundError(f"Batch source file missing: {src}")
                if dst == src:
                    raise ValueError(f"Output path cannot overwrite source file: {dst}")
                recipe = entry.get("recipe")
                if not isinstance(recipe, dict):
                    raise ValueError("Each batch entry must include a dict recipe")
                est_cost = float(entry.get("estimated_cost_usd", 0.0))
                if not math.isfinite(est_cost) or est_cost < 0:
                    raise ValueError("estimated_cost_usd must be finite and >= 0")

                src_hash = sha256(src)
                src_bytes = src.stat().st_size
                recipe_hash = canonical_hash(
                    {"source_sha256": src_hash, "output_path": str(dst), "recipe": recipe}
                )

                if recipe_hash in by_recipe_hash:
                    skipped_existing += 1
                    continue
                if str(dst) in by_output_path:
                    raise ValueError(
                        f"Conflicting recipe already targets output path: {dst}"
                    )

                run_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"fidelis-batch:{recipe_hash}"))
                item = {
                    "schema_version": self.SCHEMA_VERSION,
                    "idx": next_idx,
                    "item_id": run_id,
                    "run_id": run_id,
                    "source_path": str(src),
                    "source_sha256": src_hash,
                    "source_bytes": int(src_bytes),
                    "output_path": str(dst),
                    "recipe": recipe,
                    "recipe_hash": recipe_hash,
                    "status": "pending",
                    "paid_work_committed": False,
                    "estimated_cost_usd": est_cost,
                    "actual_cost_usd": 0.0,
                    "attempts": 0,
                    "retry_count": 0,
                    "attempt_history": [],
                    "output_sha256": None,
                    "output_bytes": 0,
                    "error_type": None,
                    "error": None,
                    "created_at_unix": time.time(),
                    "updated_at_unix": time.time(),
                }
                db.execute(
                    "INSERT INTO items (idx, item_id, recipe_hash, record) VALUES (?, ?, ?, ?)",
                    (next_idx, item["item_id"], recipe_hash, json.dumps(item, allow_nan=False)),
                )
                by_recipe_hash[recipe_hash] = item
                by_output_path[str(dst)] = item
                next_idx += 1
                enqueued += 1

        return {"enqueued": enqueued, "skipped_existing": skipped_existing}

    def _current_disk_used(self, items: list[dict[str, Any]]) -> int:
        seen_paths: set[Path] = set()
        total = 0
        for folder in (self.tmp_dir,):
            if folder.is_dir():
                for f in folder.iterdir():
                    try:
                        if f.is_file():
                            resolved = f.resolve()
                            if resolved not in seen_paths:
                                seen_paths.add(resolved)
                                total += f.stat().st_size
                    except FileNotFoundError:
                        continue
        for item in items:
            for candidate in (Path(item["output_path"]), Path(f"{item['output_path']}.recipe.json")):
                try:
                    if candidate.is_file():
                        resolved = candidate.resolve()
                        if resolved not in seen_paths:
                            seen_paths.add(resolved)
                            total += candidate.stat().st_size
                except FileNotFoundError:
                    continue
        return total

    @staticmethod
    def _total_committed_cost(items: list[dict[str, Any]]) -> float:
        total = 0.0
        for item in items:
            if item["status"] == "completed":
                total += float(item.get("actual_cost_usd") or 0.0)
            elif item.get("paid_work_committed"):
                total += float(item.get("actual_cost_usd") or item.get("estimated_cost_usd") or 0.0)
        return total

    def _verify_completed_integrity(self) -> None:
        with self._lock, self._db() as db:
            for item in self._all_items(db):
                if item["status"] != "completed":
                    continue
                out = Path(item["output_path"])
                if not out.is_file() or sha256(out) != item.get("output_sha256"):
                    item["status"] = "failed"
                    item["error_type"] = "OutputIntegrityMismatch"
                    item["error"] = (
                        "Persisted output file is missing or checksum differs from completed record"
                    )
                    self._save_item(db, item)

    def _execute_one(
        self,
        item_id: str,
        worker_fn: Callable[[BatchItemContext], dict[str, Any]],
    ) -> None:
        started = time.time()
        with self._lock, self._db() as db:
            row = db.execute("SELECT record FROM items WHERE item_id=?", (item_id,)).fetchone()
            if row is None:
                return
            item = json.loads(row[0])
            if item.get("paid_work_committed"):
                item["status"] = "needs_review"
                item["error_type"] = "DuplicatePaidWorkBlocked"
                item["error"] = "Item already committed paid/remote work; automatic re-run blocked"
                self._save_item(db, item)
                return

            was_retry = item["status"] == "failed"
            item["attempts"] += 1
            if was_retry:
                item["retry_count"] += 1
            item["status"] = "running"
            item["error_type"] = None
            item["error"] = None
            self._save_item(db, item)
            snapshot = json.loads(json.dumps(item))

        src = Path(snapshot["source_path"])
        tmp_out = self.tmp_dir / f"{snapshot['item_id']}-{snapshot['attempts']}.part"

        def mark_paid(reserved_cost: Optional[float] = None) -> None:
            with self._lock, self._db() as db:
                cur_row = db.execute(
                    "SELECT record FROM items WHERE item_id=?", (item_id,)
                ).fetchone()
                cur = json.loads(cur_row[0])
                cur["paid_work_committed"] = True
                if reserved_cost is not None:
                    cur["actual_cost_usd"] = float(reserved_cost)
                self._save_item(db, cur)

        ctx = BatchItemContext(item=snapshot, temp_output_path=tmp_out, _mark_paid=mark_paid)

        out_candidate = tmp_out
        try:
            if not src.is_file() or sha256(src) != snapshot["source_sha256"]:
                raise ValueError(
                    f"Source file missing or altered since enqueue: {snapshot['source_path']}"
                )

            result = worker_fn(ctx) or {}
            out_candidate = Path(result.get("output_path", tmp_out))
            if not out_candidate.is_file() or out_candidate.stat().st_size == 0:
                raise ValueError("Worker finished without producing a non-empty staged output")

            out_hash = sha256(out_candidate)
            out_size = int(out_candidate.stat().st_size)
            final_cost = float(result.get("actual_cost_usd", snapshot["estimated_cost_usd"]))

            dest = Path(snapshot["output_path"])
            dest.parent.mkdir(parents=True, exist_ok=True)
            sidecar_tmp = self.tmp_dir / f"{snapshot['item_id']}.recipe.json.part"
            sidecar_dest = Path(f"{dest}.recipe.json")

            record_sidecar = {
                "schema_version": 1,
                "operation": "batch_item_result",
                "run_id": snapshot["run_id"],
                "recipe_hash": snapshot["recipe_hash"],
                "source_path": snapshot["source_path"],
                "source_sha256": snapshot["source_sha256"],
                "output_path": str(dest),
                "output_sha256": out_hash,
                "recipe": snapshot["recipe"],
                "actual_cost_usd": final_cost,
                "attempt": snapshot["attempts"],
                "provenance": "unsigned_execution_record",
            }
            sidecar_bytes = (json.dumps(record_sidecar, indent=2) + "\n").encode("utf-8")

            with self._lock, self._db() as db:
                items = self._all_items(db)
                used = self._current_disk_used(items)
                in_tmp = out_candidate.resolve().parent == self.tmp_dir.resolve()
                additional = len(sidecar_bytes) + (0 if in_tmp else out_size)
                if used + additional > self.disk_budget_bytes:
                    raise BudgetExceeded(
                        f"Disk budget exceeded writing {dest.name}: {used + additional} > {self.disk_budget_bytes}"
                    )
                sidecar_tmp.write_bytes(sidecar_bytes)
                os.replace(out_candidate, dest)
                os.replace(sidecar_tmp, sidecar_dest)

            finished = time.time()
            with self._lock, self._db() as db:
                cur_row = db.execute("SELECT record FROM items WHERE item_id=?", (item_id,)).fetchone()
                cur = json.loads(cur_row[0])
                cur["status"] = "completed"
                cur["output_sha256"] = out_hash
                cur["output_bytes"] = out_size
                cur["actual_cost_usd"] = final_cost
                cur["error_type"] = None
                cur["error"] = None
                cur["attempt_history"].append(
                    {
                        "attempt": cur["attempts"],
                        "run_id": cur["run_id"],
                        "outcome": "completed",
                        "duration_s": round(finished - started, 4),
                        "cost_usd": final_cost,
                    }
                )
                self._save_item(db, cur)
        except Exception as exc:
            tmp_out.unlink(missing_ok=True)
            if out_candidate.resolve().parent == self.tmp_dir.resolve():
                out_candidate.unlink(missing_ok=True)
            finished = time.time()
            with self._lock, self._db() as db:
                cur_row = db.execute("SELECT record FROM items WHERE item_id=?", (item_id,)).fetchone()
                cur = json.loads(cur_row[0])
                committed = bool(cur.get("paid_work_committed")) or isinstance(exc, SubmissionUnknown)
                cur["paid_work_committed"] = bool(cur.get("paid_work_committed")) or isinstance(
                    exc, SubmissionUnknown
                )
                cur["status"] = "needs_review" if committed else "failed"
                cur["error_type"] = type(exc).__name__
                cur["error"] = str(exc)
                cur["attempt_history"].append(
                    {
                        "attempt": cur["attempts"],
                        "run_id": cur["run_id"],
                        "outcome": cur["status"],
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                        "duration_s": round(finished - started, 4),
                    }
                )
                self._save_item(db, cur)

    def run(
        self,
        worker_fn: Callable[[BatchItemContext], dict[str, Any]],
        *,
        retry_failed: bool = False,
        reconcile_fn: Optional[Callable[[dict[str, Any]], dict[str, Any]]] = None,
    ) -> dict[str, Any]:
        """Run pending/interrupted items with bounded workers, budgets and zero duplicate paid work."""
        if self.read_only:
            raise RuntimeError("Cannot execute on a read-only BatchRunner")

        self._verify_completed_integrity()

        if reconcile_fn is not None:
            with self._lock, self._db() as db:
                review_items = [
                    x for x in self._all_items(db) if x["status"] == "needs_review"
                ]
            for item in review_items:
                rec = reconcile_fn(item) or {}
                if rec.get("status") == "completed":
                    out_path = Path(rec.get("output_path", item["output_path"]))
                    if out_path.is_file() and out_path.stat().st_size > 0:
                        with self._lock, self._db() as db:
                            cur = json.loads(
                                db.execute(
                                    "SELECT record FROM items WHERE item_id=?", (item["item_id"],)
                                ).fetchone()[0]
                            )
                            cur["status"] = "completed"
                            cur["output_sha256"] = sha256(out_path)
                            cur["output_bytes"] = int(out_path.stat().st_size)
                            cur["actual_cost_usd"] = float(
                                rec.get("actual_cost_usd", cur.get("actual_cost_usd") or cur["estimated_cost_usd"])
                            )
                            cur["error_type"] = None
                            cur["error"] = None
                            cur["attempt_history"].append(
                                {
                                    "attempt": cur["attempts"],
                                    "run_id": cur["run_id"],
                                    "outcome": "reconciled_completed",
                                    "duration_s": 0.0,
                                }
                            )
                            self._save_item(db, cur)

        with self._lock, self._db() as db:
            all_items = self._all_items(db)
            eligible: list[dict[str, Any]] = []
            for item in all_items:
                st = item["status"]
                if st in ("pending", "interrupted"):
                    eligible.append(item)
                elif (
                    retry_failed
                    and st == "failed"
                    and not item.get("paid_work_committed")
                    and item["retry_count"] < self.max_retries
                ):
                    eligible.append(item)

        runnable_ids: list[str] = []
        with self._lock, self._db() as db:
            all_items = self._all_items(db)
            used_disk = self._current_disk_used(all_items)
            projected_cost = self._total_committed_cost(all_items)

            for item in eligible:
                if used_disk >= self.disk_budget_bytes:
                    item["status"] = "failed"
                    item["error_type"] = "BudgetExceeded"
                    item["error"] = f"Disk budget reached before dispatch ({used_disk} >= {self.disk_budget_bytes})"
                    self._save_item(db, item)
                    continue
                if (
                    self.cost_budget_usd is not None
                    and projected_cost + item["estimated_cost_usd"] > self.cost_budget_usd + 1e-12
                ):
                    item["status"] = "failed"
                    item["error_type"] = "BudgetExceeded"
                    item["error"] = (
                        f"Cost budget reached before dispatch ({projected_cost:.4f} + {item['estimated_cost_usd']:.4f} > {self.cost_budget_usd:.4f})"
                    )
                    self._save_item(db, item)
                    continue
                projected_cost += item["estimated_cost_usd"]
                runnable_ids.append(item["item_id"])

        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            inflight: set[Future] = set()
            queue = list(runnable_ids)
            while queue or inflight:
                while queue and len(inflight) < self.max_workers:
                    next_id = queue.pop(0)
                    with self._lock, self._db() as db:
                        items_now = self._all_items(db)
                        used_now = self._current_disk_used(items_now)
                        if used_now >= self.disk_budget_bytes:
                            cur = next(x for x in items_now if x["item_id"] == next_id)
                            cur["status"] = "failed"
                            cur["error_type"] = "BudgetExceeded"
                            cur["error"] = (
                                f"Disk budget exceeded during execution ({used_now} >= {self.disk_budget_bytes})"
                            )
                            self._save_item(db, cur)
                            continue
                    inflight.add(pool.submit(self._execute_one, next_id, worker_fn))
                if inflight:
                    done, inflight = wait(inflight, return_when="FIRST_COMPLETED")
                    for fut in done:
                        fut.result()

        return self.status()

    def status(self) -> dict[str, Any]:
        """Return live persisted status, retry counts, costs and disk consumption."""
        with self._lock, self._db() as db:
            items = self._all_items(db)
        counts = {name: 0 for name in sorted(VALID_STATUSES)}
        for item in items:
            counts[item["status"]] = counts.get(item["status"], 0) + 1
        return {
            "schema_version": self.SCHEMA_VERSION,
            "total_items": len(items),
            "counts": counts,
            "total_retries": sum(int(item["retry_count"]) for item in items),
            "total_cost_usd": round(self._total_committed_cost(items), 6),
            "cost_budget_usd": self.cost_budget_usd,
            "disk_used_bytes": self._current_disk_used(items),
            "disk_budget_bytes": self.disk_budget_bytes,
            "max_workers": self.max_workers,
            "max_retries": self.max_retries,
            "items": items,
        }
