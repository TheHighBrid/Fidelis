"""Loopback HTTP helpers and F07 async queue scenarios for qualification."""

from __future__ import annotations

import base64
import io
import json
import sqlite3
import time
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

import numpy as np
from PIL import Image

from fidelis.studio.mock_comfy import png_bytes

_TERMINAL_STATUSES = frozenset(
    {"completed", "failed", "cancelled", "needs_review", "waiting", "interrupted"}
)


def _npz_masks_b64(height: int, width: int) -> str:
    protected = np.zeros((height, width), dtype=np.float32)
    fabric = np.zeros((height, width), dtype=np.float32)
    confidence = np.ones((height, width), dtype=np.float32)
    protected[: height // 2, : width // 2] = 1.0
    fabric[height // 2 :, width // 2 :] = 1.0
    buf = io.BytesIO()
    np.savez(buf, protected=protected, fabric=fabric, confidence=confidence)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def http_json(
    base_url: str, path: str, payload: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Perform a loopback-only JSON HTTP request against the local Studio server."""
    if not base_url.startswith("http://127.0.0.1:"):
        raise ValueError(f"Refusing non-loopback Studio URL: {base_url}")
    headers = {"Origin": base_url}
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = Request(base_url + path, data=data, headers=headers)
    with urlopen(req, timeout=10) as resp:  # nosec B310
        return json.load(resp)


def http_png_array(base_url: str, path: str) -> np.ndarray:
    """Fetch and decode a loopback-only PNG export into an RGB uint8 array."""
    if not base_url.startswith("http://127.0.0.1:"):
        raise ValueError(f"Refusing non-loopback Studio URL: {base_url}")
    req = Request(base_url + path, headers={"Origin": base_url})
    with urlopen(req, timeout=15) as resp:  # nosec B310
        raw = resp.read()
    with Image.open(io.BytesIO(raw)) as img:
        return np.asarray(img.convert("RGB"), dtype=np.uint8)


def create_job(
    base_url: str, base: np.ndarray, texture: np.ndarray, label: str
) -> dict[str, Any]:
    """Create a regional Studio job with explicit protection and fabric masks."""
    h, w, _ = base.shape
    payload = {
        "label": label,
        "profile": "luxury_apparel",
        "base": base64.b64encode(png_bytes(base)).decode("ascii"),
        "texture": base64.b64encode(png_bytes(texture)).decode("ascii"),
        "masks": _npz_masks_b64(h, w),
    }
    return http_json(base_url, "/api/regions/jobs", payload)


def wait_task(
    base_url: str,
    job_id: str,
    task_id: str,
    *,
    deadline_seconds: float,
    measure_responsiveness: bool = False,
) -> tuple[dict[str, Any], float]:
    """Poll a generation task until terminal status and measure poll latency."""
    deadline = time.monotonic() + deadline_seconds
    max_latency_ms = 0.0
    while time.monotonic() < deadline:
        if measure_responsiveness:
            t0 = time.monotonic()
            http_json(base_url, "/api/regions/jobs")
            max_latency_ms = max(max_latency_ms, (time.monotonic() - t0) * 1000.0)
        task = http_json(base_url, f"/api/regions/jobs/{job_id}/generations/{task_id}")
        if task["status"] in _TERMINAL_STATUSES:
            return task, round(max_latency_ms, 2)
        time.sleep(0.05)
    raise TimeoutError(f"Timed out waiting for task {task_id}")


def read_run_record(runs_root: Path, run_id: str) -> dict[str, Any] | None:
    """Read a persisted generation run record from the local SQLite ledger."""
    db_path = runs_root / "generation.sqlite3"
    if not db_path.is_file():
        return None
    uri = db_path.resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=2)
    try:
        row = conn.execute("SELECT record FROM runs WHERE id=?", (run_id,)).fetchone()
        return json.loads(row[0]) if row else None
    except sqlite3.Error:
        return None
    finally:
        conn.close()


def verify_protected_and_unknown_pixels(
    base_url: str, job_id: str, expected_base: np.ndarray
) -> dict[str, Any]:
    """Verify exact pixel preservation across protected and unclassified regions."""
    h, w, _ = expected_base.shape
    master = http_png_array(base_url, f"/api/regions/jobs/{job_id}/export?role=master")
    exported_base = http_png_array(base_url, f"/api/regions/jobs/{job_id}/export?role=base")
    if master.shape != expected_base.shape or exported_base.shape != expected_base.shape:
        raise AssertionError(f"Dimension mismatch: master={master.shape}, base={expected_base.shape}")
    prot_slice = (slice(0, h // 2), slice(0, w // 2))
    unknown_tr = (slice(0, h // 2), slice(w // 2, w))
    unknown_bl = (slice(h // 2, h), slice(0, w // 2))
    prot_mismatch = int(np.sum(np.any(master[prot_slice] != exported_base[prot_slice], axis=-1)))
    unk_mismatch = int(
        np.sum(np.any(master[unknown_tr] != exported_base[unknown_tr], axis=-1))
        + np.sum(np.any(master[unknown_bl] != exported_base[unknown_bl], axis=-1))
    )
    if prot_mismatch != 0 or unk_mismatch != 0:
        raise AssertionError(f"Pixel invariant violated: protected={prot_mismatch}, unknown={unk_mismatch}")
    return {
        "dimensions": [int(w), int(h)],
        "protected_pixel_mismatches": prot_mismatch,
        "unknown_pixel_mismatches": unk_mismatch,
    }


def scenario_responsiveness_and_apply(
    base_url: str, base: np.ndarray, texture: np.ndarray, deadline_seconds: float
) -> dict[str, Any]:
    """Run Scenario 1: responsive HTTP polling and protected auto-apply."""
    job1 = create_job(base_url, base, texture, "f07-responsive-apply")
    t1 = http_json(base_url, f"/api/regions/jobs/{job1['id']}/generations", {"expected_revision": 1})
    t1_done, max_http_ms = wait_task(
        base_url, job1["id"], t1["id"], deadline_seconds=deadline_seconds, measure_responsiveness=True
    )
    if t1_done["status"] != "completed":
        raise AssertionError(f"Scenario 1 expected completed, got {t1_done}")
    job1_after = http_json(base_url, f"/api/regions/jobs/{job1['id']}")
    if job1_after["revision"] != 2:
        raise AssertionError(f"Scenario 1 expected revision 2, got {job1_after['revision']}")
    pixels = verify_protected_and_unknown_pixels(base_url, job1["id"], base)
    return {
        "job_id": job1["id"],
        "task_id": t1["id"],
        "run_id": t1["run_id"],
        "prompt_id": t1_done.get("prompt_id"),
        "status": t1_done["status"],
        "result_revision": job1_after["revision"],
        "max_http_poll_latency_ms": max_http_ms,
        **pixels,
    }


def scenario_scoped_cancel(
    base_url: str, base: np.ndarray, texture: np.ndarray, deadline_seconds: float
) -> dict[str, Any]:
    """Run Scenario 2: cancel owned job without interrupting an unrelated peer."""
    job2 = create_job(base_url, base, texture, "f07-cancel-target")
    job3 = create_job(base_url, base, texture, "f07-unrelated-peer")
    t2 = http_json(base_url, f"/api/regions/jobs/{job2['id']}/generations", {"expected_revision": 1})
    t3 = http_json(base_url, f"/api/regions/jobs/{job3['id']}/generations", {"expected_revision": 1})
    t2_cancel = http_json(
        base_url, f"/api/regions/jobs/{job2['id']}/generations/{t2['id']}/cancel", {}
    )
    t2_final, _ = wait_task(base_url, job2["id"], t2["id"], deadline_seconds=deadline_seconds)
    t3_final, _ = wait_task(base_url, job3["id"], t3["id"], deadline_seconds=deadline_seconds)
    if t2_cancel["status"] != "cancelled" or t2_final["status"] != "cancelled":
        raise AssertionError(f"Scenario 2 cancel failed: {t2_cancel}, {t2_final}")
    if http_json(base_url, f"/api/regions/jobs/{job2['id']}")["revision"] != 1:
        raise AssertionError("Cancelled job revision mutated")
    if t3_final["status"] != "completed":
        raise AssertionError(f"Unrelated peer interrupted: {t3_final}")
    pixels = verify_protected_and_unknown_pixels(base_url, job3["id"], base)
    return {
        "cancelled_job_id": job2["id"],
        "cancelled_task_id": t2["id"],
        "cancelled_status": t2_final["status"],
        "remote_may_continue_disclosed": bool(t2_final.get("remote_may_continue")),
        "unrelated_job_id": job3["id"],
        "unrelated_task_id": t3["id"],
        "unrelated_status": t3_final["status"],
        "unrelated_prompt_id": t3_final.get("prompt_id"),
        **pixels,
    }


def wait_persisted_prompt_id(runs_root: Path, run_id: str, timeout_s: float) -> str:
    """Poll the SQLite runs ledger until `prompt_id` is persisted."""
    poll_end = time.monotonic() + timeout_s
    while time.monotonic() < poll_end:
        rec = read_run_record(runs_root, run_id)
        if rec and isinstance(rec.get("prompt_id"), str) and rec["prompt_id"]:
            return rec["prompt_id"]
        time.sleep(0.01)
    raise AssertionError("Did not observe persisted prompt_id before restart")


def _assert_resume_completed(
    restarted_url: str,
    runs_root: Path,
    ids: tuple[str, str, str, str],
    deadline_seconds: float,
) -> tuple[str, dict[str, Any], str]:
    job_id, task_id, run_id, before_prompt_id = ids
    t4_restarted = http_json(restarted_url, f"/api/regions/jobs/{job_id}/generations/{task_id}")
    if t4_restarted["status"] != "interrupted":
        raise AssertionError(f"Expected interrupted after restart, got {t4_restarted['status']}")
    if http_json(restarted_url, f"/api/regions/jobs/{job_id}")["revision"] != 1:
        raise AssertionError("Interrupted job should not auto-apply before explicit resume")
    t4_resumed = http_json(
        restarted_url, f"/api/regions/jobs/{job_id}/generations/{task_id}/resume", {}
    )
    if t4_resumed["status"] != "queued":
        raise AssertionError(f"Expected queued after resume, got {t4_resumed['status']}")
    t4_done, _ = wait_task(restarted_url, job_id, task_id, deadline_seconds=deadline_seconds)
    if t4_done["status"] != "completed":
        raise AssertionError(f"Scenario 3 expected completed, got {t4_done}")
    rec_after = read_run_record(runs_root, run_id)
    after_prompt_id = rec_after.get("prompt_id") if rec_after else None
    if after_prompt_id != before_prompt_id:
        raise AssertionError(f"Duplicate submission detected: {before_prompt_id} != {after_prompt_id}")
    return str(t4_restarted["status"]), t4_done, str(after_prompt_id)


def scenario_restart_recovery_resume(
    restarted_url: str,
    runs_root: Path,
    base: np.ndarray,
    ids: tuple[str, str, str, str],
    deadline_seconds: float,
) -> dict[str, Any]:
    """Run Scenario 3b: resume interrupted task and confirm single prompt_id."""
    job_id, task_id, run_id, before_prompt_id = ids
    status_after_restart, t4_done, after_prompt_id = _assert_resume_completed(
        restarted_url, runs_root, ids, deadline_seconds
    )
    pixels = verify_protected_and_unknown_pixels(restarted_url, job_id, base)
    return {
        "job_id": job_id,
        "task_id": task_id,
        "run_id": run_id,
        "status_after_restart": status_after_restart,
        "final_status": t4_done["status"],
        "before_prompt_id": before_prompt_id,
        "after_prompt_id": after_prompt_id,
        "single_prompt_id_preserved": after_prompt_id == before_prompt_id,
        **pixels,
    }
