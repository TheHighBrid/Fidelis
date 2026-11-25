"""End-to-end F07 async queue qualification harness over loopback Studio HTTP."""

from __future__ import annotations

import hashlib
import io
import json
import shutil
import socket
import subprocess  # nosec B404
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import URLError

import numpy as np
from PIL import Image

from fidelis.studio.async_scenarios import (
    create_job,
    http_json,
    scenario_responsiveness_and_apply,
    scenario_restart_recovery_resume,
    scenario_scoped_cancel,
    wait_persisted_prompt_id,
)
from fidelis.studio.mock_comfy import MockComfyServer
from fidelis.studio.worker_preflight import run_worker_preflight

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "fidelis.f07_async_qualification.v1"
DEFAULT_COMFY_ADDRESS = "http://127.0.0.1:8188"


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _build_test_images(
    source_path: Path | None, max_edge: int
) -> tuple[np.ndarray, np.ndarray, str | None]:
    if source_path is not None:
        raw = source_path.read_bytes()
        src_sha = hashlib.sha256(raw).hexdigest()
        with Image.open(io.BytesIO(raw)) as img:
            rgb = img.convert("RGB")
            if max(rgb.size) > max_edge:
                rgb.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
            base = np.asarray(rgb, dtype=np.uint8)
    else:
        src_sha = None
        yy, xx = np.mgrid[0:96, 0:96]
        base = np.stack(
            [
                ((xx * 3 + yy) % 200 + 25).astype(np.uint8),
                ((yy * 2 + 40) % 200 + 25).astype(np.uint8),
                (((xx ^ yy) * 4) % 200 + 25).astype(np.uint8),
            ],
            axis=-1,
        )
    texture = np.clip(base.astype(np.int16) + 12, 0, 255).astype(np.uint8)
    return base, texture, src_sha


def _same_grid_realesr_bundle() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "family": "other",
        "input_node": "1",
        "output_node": "4",
        "workflow": {
            "1": {"class_type": "LoadImage", "inputs": {"image": "input.png"}},
            "2": {
                "class_type": "UpscaleModelLoader",
                "inputs": {"model_name": "realesr-general-x4v3.pth"},
            },
            "3": {
                "class_type": "ImageUpscaleWithModel",
                "inputs": {"upscale_model": ["2", 0], "image": ["1", 0]},
            },
            "5": {
                "class_type": "ImageScaleBy",
                "inputs": {"image": ["3", 0], "upscale_method": "area", "scale_by": 0.25},
            },
            "4": {
                "class_type": "SaveImage",
                "inputs": {"images": ["5", 0], "filename_prefix": "fidelis-f07"},
            },
        },
    }


def _fixture_bundle() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "family": "other",
        "input_node": "1",
        "output_node": "3",
        "workflow": {
            "1": {"class_type": "LoadImage", "inputs": {"image": "input.png"}},
            "2": {"class_type": "FixtureTexture", "inputs": {"image": ["1", 0]}},
            "3": {
                "class_type": "SaveImage",
                "inputs": {"images": ["2", 0], "filename_prefix": "fidelis-f07-fix"},
            },
        },
    }


def _spawn_studio_process(tail: list[str]) -> subprocess.Popen[bytes]:
    # B603: use literal absolute env paths so argv[0] is statically verified.
    if Path("/usr/bin/env").is_file():
        return subprocess.Popen(  # nosec B603
            ["/usr/bin/env", *tail], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
    if Path("/bin/env").is_file():
        return subprocess.Popen(  # nosec B603
            ["/bin/env", *tail], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
    if Path("/data/data/com.termux/files/usr/bin/env").is_file():
        return subprocess.Popen(  # nosec B603
            ["/data/data/com.termux/files/usr/bin/env", *tail],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    raise RuntimeError("No absolute env binary found to launch Studio subprocess")


class _StudioProcess:
    """Manage a `scripts/web-ui.py` subprocess bound to `127.0.0.1`."""

    def __init__(
        self,
        *,
        workspace: Path,
        generation_root: Path,
        workflow_path: Path,
        comfy_address: str,
    ) -> None:
        self.port = _free_port()
        self.address = f"http://127.0.0.1:{self.port}"
        tail = [
            sys.executable,
            str(REPO_ROOT / "scripts" / "web-ui.py"),
            "--bind",
            "127.0.0.1",
            "--port",
            str(self.port),
            "--region-workspace",
            str(workspace),
            "--generation-root",
            str(generation_root),
            "--texture-workflow",
            str(workflow_path),
            "--comfy-address",
            comfy_address,
        ]
        self.proc = _spawn_studio_process(tail)
        self._wait_ready()

    def _wait_ready(self) -> None:
        deadline = time.monotonic() + 15.0
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError(f"web-ui.py exited early with code {self.proc.returncode}")
            try:
                if http_json(self.address, "/api/regions/jobs").get("generation_enabled") is True:
                    return
            except (OSError, URLError):
                time.sleep(0.05)
        self.stop(force=True)
        raise TimeoutError("Timed out waiting for Studio server startup")

    def stop(self, *, force: bool = False) -> int | None:
        if self.proc.poll() is not None:
            return self.proc.returncode
        if force:
            self.proc.kill()
        else:
            self.proc.terminate()
        try:
            return self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            return self.proc.wait(timeout=5)


def _restart_submit(
    server: _StudioProcess,
    runs_root: Path,
    base: np.ndarray,
    texture: np.ndarray,
    deadline_seconds: float,
) -> tuple[str, str, str, str]:
    job4 = create_job(server.address, base, texture, "f07-restart-resume")
    t4 = http_json(
        server.address, f"/api/regions/jobs/{job4['id']}/generations", {"expected_revision": 1}
    )
    before_prompt_id = wait_persisted_prompt_id(runs_root, t4["run_id"], min(30.0, deadline_seconds))
    server.stop(force=True)
    return job4["id"], t4["id"], t4["run_id"], before_prompt_id


def _run_scenarios(
    *,
    workspace: Path,
    generation_root: Path,
    workflow_path: Path,
    comfy_address: str,
    base: np.ndarray,
    texture: np.ndarray,
    deadline_seconds: float,
) -> dict[str, Any]:
    runs_root = generation_root / "runs"
    server = _StudioProcess(
        workspace=workspace,
        generation_root=generation_root,
        workflow_path=workflow_path,
        comfy_address=comfy_address,
    )
    try:
        s1 = scenario_responsiveness_and_apply(server.address, base, texture, deadline_seconds)
        s2 = scenario_scoped_cancel(server.address, base, texture, deadline_seconds)
        ids = _restart_submit(server, runs_root, base, texture, deadline_seconds)
    except BaseException:
        server.stop(force=True)
        raise

    restarted = _StudioProcess(
        workspace=workspace,
        generation_root=generation_root,
        workflow_path=workflow_path,
        comfy_address=comfy_address,
    )
    try:
        s3 = scenario_restart_recovery_resume(
            restarted.address, runs_root, base, ids, deadline_seconds
        )
    finally:
        restarted.stop(force=False)
    return {
        "responsiveness_and_apply": s1,
        "scoped_cancel_no_global_interrupt": s2,
        "restart_recovery_single_prompt": s3,
    }


def _prepare_bundle(work_root: Path, workflow_path: Path | None, fixture: bool) -> tuple[Path, str]:
    bundle_path = work_root / "workflow.json"
    if workflow_path is not None:
        bundle = json.loads(workflow_path.read_text(encoding="utf-8"))
    else:
        bundle = _fixture_bundle() if fixture else _same_grid_realesr_bundle()
    bundle_bytes = json.dumps(bundle, sort_keys=True, separators=(",", ":")).encode("utf-8")
    bundle_path.write_bytes(bundle_bytes)
    return bundle_path, hashlib.sha256(bundle_bytes).hexdigest()


def _execute_mode(
    *,
    fixture: bool,
    address: str,
    workspace: Path,
    generation_root: Path,
    bundle_path: Path,
    base: np.ndarray,
    texture: np.ndarray,
    deadline_seconds: float,
) -> tuple[dict[str, Any], str, str, dict[str, Any]]:
    if fixture:
        with MockComfyServer() as mock:
            scenarios = _run_scenarios(
                workspace=workspace,
                generation_root=generation_root,
                workflow_path=bundle_path,
                comfy_address=mock.address,
                base=base,
                texture=texture,
                deadline_seconds=deadline_seconds,
            )
            extra = {
                "fixture_interrupt_calls": mock.interrupt_calls,
                "fixture_prompt_submissions": mock.prompt_submissions,
            }
        return scenarios, "fixture_mock_worker", "E1_fixture_async_queue_tested", extra

    preflight = run_worker_preflight(REPO_ROOT, address=address, workflow_path=bundle_path, timeout=3.0)
    preflight_status = preflight["preflight_status"]
    if preflight_status != "qualified_preflight":
        raise RuntimeError(f"Worker preflight failed ({preflight_status}): {preflight.get('failures')}")
    scenarios = _run_scenarios(
        workspace=workspace,
        generation_root=generation_root,
        workflow_path=bundle_path,
        comfy_address=address,
        base=base,
        texture=texture,
        deadline_seconds=deadline_seconds,
    )
    return scenarios, preflight_status, "E2_live_async_queue_verified", {"preflight": preflight}


def _build_receipt(
    *,
    fixture: bool,
    address: str,
    preflight_status: str,
    evidence_level: str,
    scenarios: dict[str, Any],
    metadata: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "mode": "fixture" if fixture else "live",
        "evidence_level": evidence_level,
        "live_quality_verified": False,
        "e3_visual_accepted": False,
        "worker_address": "fixture://127.0.0.1" if fixture else address,
        "preflight_status": preflight_status,
        "scenarios": scenarios,
        **metadata,
    }


def _reset_dirs(work_root: Path) -> tuple[Path, Path]:
    workspace = work_root / "region_jobs"
    generation_root = work_root / "async_generation"
    for stale in (workspace, generation_root):
        if stale.exists():
            shutil.rmtree(stale)
    return workspace, generation_root


def run_qualification(
    *,
    fixture: bool = False,
    address: str = DEFAULT_COMFY_ADDRESS,
    workflow_path: Path | None = None,
    source_path: Path | None = None,
    evidence_dir: Path | None = None,
    output_path: Path | None = None,
    max_edge: int = 256,
    deadline_seconds: float = 120.0,
) -> dict[str, Any]:
    """Execute all F07 async Studio scenarios and return a structured receipt."""
    temp_dir = None if evidence_dir is not None else tempfile.TemporaryDirectory(prefix="fidelis-f07-")
    work_root = evidence_dir if evidence_dir is not None else Path(temp_dir.name)
    work_root.mkdir(parents=True, exist_ok=True)
    try:
        workspace, generation_root = _reset_dirs(work_root)
        base, texture, src_sha = _build_test_images(source_path, max_edge=max_edge)
        bundle_path, workflow_sha256 = _prepare_bundle(work_root, workflow_path, fixture)
        scenarios, preflight_status, evidence_level, extra = _execute_mode(
            fixture=fixture,
            address=address,
            workspace=workspace,
            generation_root=generation_root,
            bundle_path=bundle_path,
            base=base,
            texture=texture,
            deadline_seconds=deadline_seconds,
        )
        metadata = {
            "workflow_sha256": workflow_sha256,
            "source_sha256": src_sha,
            "input_dimensions": [int(base.shape[1]), int(base.shape[0])],
            **extra,
        }
        receipt = _build_receipt(
            fixture=fixture,
            address=address,
            preflight_status=preflight_status,
            evidence_level=evidence_level,
            scenarios=scenarios,
            metadata=metadata,
        )
        if output_path is not None:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
        return receipt
    finally:
        if temp_dir is not None:
            temp_dir.cleanup()
