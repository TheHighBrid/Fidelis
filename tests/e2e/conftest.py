"""Shared deterministic fixtures and helpers for Fidelis E2E tests (Tiers 1-4)."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Sequence

import cv2
import numpy as np
import pytest
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[2]
PRODUCT_EDGES_REAL = REPO_ROOT / "experiments" / "eval_crops" / "product_edges_real.png"
FASHION_FABRIC_REAL = REPO_ROOT / "experiments" / "eval_crops" / "fashion_fabric_real.png"


def pytest_configure(config: pytest.Config) -> None:
    """Register E2E tier and feature markers without modifying pyproject.toml."""
    markers = [
        "tier1: Tier 1 per-feature E2E tests (F1-F10)",
        "tier2: Tier 2 boundary and corner-case E2E tests (F1-F10)",
        "tier3: Tier 3 cross-feature combination E2E tests",
        "tier4: Tier 4 real-world scenario E2E tests",
        "f1: Feature F1 - Explicit 4x Bicubic Comparator",
        "f2: Feature F2 - Scale-Matched Interior Texture Retention Metric",
        "f3: Feature F3 - Oversharpening & Halo Restraint Metric",
        "f4: Feature F4 - Fabric Weave & Hardware Faithfulness Metrics",
        "f5: Feature F5 - Texture Guard & Pixel-Lock Preservation",
        "f6: Feature F6 - Contour vs. Interior Texture ROI Separation",
        "f7: Feature F7 - Pluggable Restoration Model Runner",
        "f8: Feature F8 - Model-vs-Bicubic Audition Harness",
        "f9: Feature F9 - Coffee 1000x1000 Regression Case",
        "f10: Feature F10 - Melato Fabric & Hardware Evaluation Protocol",
    ]
    for marker in markers:
        config.addinivalue_line("markers", marker)


def save_rgb_png(arr: np.ndarray, path: Path) -> Path:
    """Save a uint8 HxWx3 RGB numpy array as an uncompressed/standard PNG."""
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(np.asarray(arr, dtype=np.uint8), mode="RGB").save(path, format="PNG")
    return path


def load_rgb_png(path: Path) -> np.ndarray:
    """Load an image file as a uint8 HxWx3 RGB numpy array."""
    with Image.open(path) as img:
        return np.asarray(img.convert("RGB"), dtype=np.uint8)


def sha256_file(path: Path) -> str:
    """Compute SHA-256 hex digest of a file."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_crema_and_rim_1x(w: int = 128, h: int = 128, seed: int = 42) -> np.ndarray:
    """Generate deterministic 1x RGB image with fine coffee-crema texture and hard cup rim.

    - Interior region: moderate-gradient, multi-frequency micro-texture (crema bubbles).
    - Rim & spoon hardware: high-contrast sharp contour transitions.
    """
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    cy, cx = h * 0.5, w * 0.5
    radius = min(w, h) * 0.38
    dist = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)

    # Background: warm dark espresso table
    img = np.zeros((h, w, 3), dtype=np.float32)
    img[..., 0] = 32.0
    img[..., 1] = 24.0
    img[..., 2] = 20.0

    # Cup rim: bright crisp porcelain ring
    rim_mask = (dist >= radius - max(2.0, min(w, h) * 0.03)) & (dist <= radius + max(2.0, min(w, h) * 0.03))
    img[rim_mask] = [235.0, 232.0, 226.0]

    # Coffee crema interior: fine uneven micro-texture + subtle bubbles
    crema_mask = dist < (radius - max(2.0, min(w, h) * 0.03))
    micro_tex = (
        14.0 * np.sin(2.0 * np.pi * xx / 5.0 + 0.3 * np.sin(yy / 7.0))
        + 10.0 * np.cos(2.0 * np.pi * yy / 4.5)
        + 8.0 * np.sin(2.0 * np.pi * (xx + yy) / 6.0)
        + rng.normal(0.0, 9.0, size=(h, w)).astype(np.float32)
    )
    img[crema_mask, 0] = 165.0 + micro_tex[crema_mask]
    img[crema_mask, 1] = 112.0 + 0.85 * micro_tex[crema_mask]
    img[crema_mask, 2] = 68.0 + 0.65 * micro_tex[crema_mask]

    # Hard metallic spoon bar on the right side
    sx0, sx1 = int(w * 0.78), min(w - 1, int(w * 0.90))
    sy0, sy1 = int(h * 0.15), int(h * 0.85)
    if sx1 > sx0 and sy1 > sy0:
        img[sy0:sy1, sx0:sx1] = [195.0, 198.0, 205.0]
        mid_x = (sx0 + sx1) // 2
        img[sy0:sy1, sx0:mid_x] = [145.0, 148.0, 155.0]

    return np.clip(np.round(img), 0, 255).astype(np.uint8)


def make_fabric_and_hardware_1x(w: int = 128, h: int = 128, seed: int = 43) -> np.ndarray:
    """Generate deterministic 1x RGB image with oriented textile weave, stitching seam, and hardware."""
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)

    # Diagonal twill textile weave across left/center
    diag = (xx + yy) * (2.0 * np.pi / 4.5)
    cross = (xx - yy) * (2.0 * np.pi / 9.0)
    weave = 18.0 * np.sin(diag) + 7.0 * np.cos(cross) + rng.normal(0.0, 2.5, size=(h, w)).astype(np.float32)

    img = np.zeros((h, w, 3), dtype=np.float32)
    img[..., 0] = 74.0 + weave
    img[..., 1] = 82.0 + weave * 0.95
    img[..., 2] = 98.0 + weave * 0.90

    # Vertical stitching seam around x = 62%
    seam_x = int(w * 0.62)
    if 2 <= seam_x < w - 2:
        img[:, seam_x - 1 : seam_x + 2] = [45.0, 48.0, 56.0]
        for y in range(2, h - 2, 6):
            img[y : min(h, y + 3), seam_x] = [215.0, 210.0, 195.0]

    # Metallic hardware (zipper/buckle) on right quadrant
    hx0, hx1 = int(w * 0.72), min(w - 2, int(w * 0.92))
    hy0, hy1 = int(h * 0.25), int(h * 0.75)
    if hx1 > hx0 + 2 and hy1 > hy0 + 2:
        img[hy0:hy1, hx0:hx1] = [180.0, 184.0, 190.0]
        img[hy0 + 2 : hy1 - 2, hx0 + 2 : hx1 - 2] = [110.0, 114.0, 120.0]
        # Crisp specular bar
        bar_y = (hy0 + hy1) // 2
        img[max(0, bar_y - 2) : min(h, bar_y + 2), hx0:hx1] = [238.0, 240.0, 244.0]

    return np.clip(np.round(img), 0, 255).astype(np.uint8)


def _target_wh(src_1x: np.ndarray, target_size: tuple[int, int] | None, scale: int = 4) -> tuple[int, int]:
    if target_size is not None:
        return int(target_size[0]), int(target_size[1])
    h, w = src_1x.shape[:2]
    return w * scale, h * scale


def make_bicubic_4x(
    src_1x: np.ndarray,
    target_size: tuple[int, int] | None = None,
    scale: int = 4,
) -> np.ndarray:
    """Generate deterministic 4x PIL Image.Resampling.BICUBIC baseline."""
    tw, th = _target_wh(src_1x, target_size, scale=scale)
    pil = Image.fromarray(np.asarray(src_1x, dtype=np.uint8), mode="RGB")
    return np.asarray(pil.resize((tw, th), Image.Resampling.BICUBIC), dtype=np.uint8)


def make_lanczos_4x(
    src_1x: np.ndarray,
    target_size: tuple[int, int] | None = None,
    scale: int = 4,
) -> np.ndarray:
    """Generate deterministic 4x PIL Image.Resampling.LANCZOS baseline."""
    tw, th = _target_wh(src_1x, target_size, scale=scale)
    pil = Image.fromarray(np.asarray(src_1x, dtype=np.uint8), mode="RGB")
    return np.asarray(pil.resize((tw, th), Image.Resampling.LANCZOS), dtype=np.uint8)


def make_smoothed_4x(
    src_1x: np.ndarray,
    sigma: float = 2.4,
    target_size: tuple[int, int] | None = None,
    scale: int = 4,
) -> np.ndarray:
    """Generate 4x output that loses interior micro-texture (simulating crema smoothing)."""
    bic = make_bicubic_4x(src_1x, target_size=target_size, scale=scale)
    k = max(3, int(round(sigma * 4)) | 1)
    blurred = cv2.GaussianBlur(bic, (k, k), sigmaX=sigma, sigmaY=sigma)
    return np.asarray(blurred, dtype=np.uint8)


def make_oversharpened_4x(
    src_1x: np.ndarray,
    amount: float = 2.6,
    sigma: float = 1.6,
    target_size: tuple[int, int] | None = None,
    scale: int = 4,
) -> np.ndarray:
    """Generate 4x output with edge overshoot/undershoot halos and elevated Nyquist energy."""
    bic = make_bicubic_4x(src_1x, target_size=target_size, scale=scale).astype(np.float32)
    blurred = cv2.GaussianBlur(bic, (0, 0), sigmaX=sigma, sigmaY=sigma)
    sharpened = bic + amount * (bic - blurred)
    # Add subtle Nyquist checkerboard ringing along high-frequency bands
    h, w = bic.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w]
    nyquist = (((xx + yy) % 2) * 2.0 - 1.0)[..., None] * 6.0
    return np.clip(np.round(sharpened + nyquist), 0, 255).astype(np.uint8)


def make_enhanced_4x(
    src_1x: np.ndarray,
    detail_gain: float = 10.0,
    seed: int = 99,
    target_size: tuple[int, int] | None = None,
    scale: int = 4,
) -> np.ndarray:
    """Generate 4x output with genuine mid-band interior micro-detail gain and clean contours.

    Enhances moderate-gradient interior texture without creating hard-edge overshoot/halos.
    """
    bic = make_bicubic_4x(src_1x, target_size=target_size, scale=scale).astype(np.float32)
    h, w = bic.shape[:2]

    # Identify hard edges to keep overshoot-free
    gray = cv2.cvtColor(bic.astype(np.uint8), cv2.COLOR_RGB2GRAY).astype(np.float32)
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    grad = np.sqrt(gx * gx + gy * gy)
    interior_weight = np.clip(1.0 - grad / 60.0, 0.0, 1.0)

    # Mid-band detail at 4x (wavelength ~6-10 px, well below Nyquist)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    rng = np.random.default_rng(seed)
    midband = (
        0.6 * np.sin(2.0 * np.pi * xx / 7.0 + 0.4 * np.cos(yy / 9.0))
        + 0.4 * np.cos(2.0 * np.pi * yy / 6.5)
        + rng.normal(0.0, 0.25, size=(h, w)).astype(np.float32)
    )
    # Band-pass smooth slightly so it has zero Nyquist spike
    midband = cv2.GaussianBlur(midband, (3, 3), sigmaX=0.8)
    delta = (detail_gain * midband * interior_weight)[..., None]
    return np.clip(np.round(bic + delta), 0, 255).astype(np.uint8)


@pytest.fixture
def crema_and_rim_1x() -> np.ndarray:
    return make_crema_and_rim_1x(128, 128, seed=42)


@pytest.fixture
def fabric_and_hardware_1x() -> np.ndarray:
    return make_fabric_and_hardware_1x(128, 128, seed=43)


@pytest.fixture
def product_edges_real_path() -> Path:
    assert PRODUCT_EDGES_REAL.is_file(), f"Missing real fixture: {PRODUCT_EDGES_REAL}"
    return PRODUCT_EDGES_REAL


@pytest.fixture
def fashion_fabric_real_path() -> Path:
    assert FASHION_FABRIC_REAL.is_file(), f"Missing real fixture: {FASHION_FABRIC_REAL}"
    return FASHION_FABRIC_REAL


@pytest.fixture
def run_cli() -> Callable[..., subprocess.CompletedProcess[str]]:
    def _run(
        script_rel_path: str,
        args: Sequence[str],
        *,
        check: bool = False,
        timeout: int = 60,
    ) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(REPO_ROOT)
        cmd = [sys.executable, str(REPO_ROOT / script_rel_path), *args]
        return subprocess.run(
            cmd,
            cwd=str(REPO_ROOT),
            env=env,
            text=True,
            capture_output=True,
            check=check,
            timeout=timeout,
        )

    return _run


def load_benchmark_protocol_and_slots() -> tuple[dict[str, Any], dict[str, Any]]:
    """Load canonical benchmark protocol-v1 and slots-v1 manifests."""
    protocol = json.loads((REPO_ROOT / "config" / "benchmark" / "protocol-v1.json").read_text(encoding="utf-8"))
    slots = json.loads((REPO_ROOT / "config" / "benchmark" / "slots-v1.json").read_text(encoding="utf-8"))
    return protocol, slots


def build_single_case_manifest(
    *,
    case_id: str,
    rel_source_path: str,
    category: str,
    source_dimensions: list[int],
    target_dimensions: list[int],
    rois: list[dict[str, Any]],
    asset_root: Path | None = None,
    split: str = "held_out",
) -> dict[str, Any]:
    """Build a valid v1 regression manifest dict for run_comparators / CLI tests."""
    from fidelis.eval.corpus_manifest import digest, inspect_image

    protocol, slots = load_benchmark_protocol_and_slots()
    if asset_root is not None and (asset_root / rel_source_path).is_file():
        source_info = {"path": rel_source_path, **inspect_image(asset_root / rel_source_path)}
    else:
        source_info = {"path": rel_source_path, "dimensions": source_dimensions}

    return {
        "schema_version": 1,
        "id": f"e2e-{case_id}",
        "protocol_sha256": digest(protocol),
        "slots_sha256": digest(slots),
        "cases": [
            {
                "id": case_id,
                "role": "regression",
                "slot_id": None,
                "category": category,
                "split": split,
                "source_kind": "photograph",
                "leakage_group": f"e2e-{case_id}",
                "source": source_info,
                "source_path": rel_source_path,
                "source_dimensions": source_dimensions,
                "target_dimensions": target_dimensions,
                "expected_behavior": "enhance",
                "rois": rois,
                "known_text": [],
                "text_review": "completed",
                "rights": {
                    "status": "unknown",
                    "local_evaluation": True,
                    "subject_consent": "not_required",
                    "remote_processing": "denied",
                },
                "coverage_review": {"status": "approved"},
            }
        ],
    }
