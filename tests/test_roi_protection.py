"""Regression tests for F10 (MEL-64) structural ROI protection and internal drift screening."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import numpy as np
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from fidelis.postprocess.regions import RegionBlend, compose_regions  # noqa: E402
from fidelis.postprocess.roi_protection import (  # noqa: E402
    build_roi_protection_masks,
    screen_internal_drift,
    validate_rois,
)


def _textured_scene(height: int = 192, width: int = 192) -> np.ndarray:
    """Create a deterministic scene with centered high-contrast logo/hardware geometry."""
    yy, xx = np.indices((height, width))
    arr = np.zeros((height, width, 3), dtype=np.uint8)
    arr[:, :, 0] = (90 + ((xx * 5 + yy * 3) % 40)).astype(np.uint8)
    arr[:, :, 1] = (100 + ((xx * 2 + yy * 7) % 35)).astype(np.uint8)
    arr[:, :, 2] = (110 + ((xx + yy * 4) % 30)).astype(np.uint8)
    cy, cx = height // 2, width // 2
    y0, y1 = max(8, cy - 16), min(height - 8, cy + 16)
    x0, x1 = max(8, cx - 16), min(width - 8, cx + 16)
    arr[y0:y1, x0:x1] = (30, 35, 45)
    for y in range(y0 + 2, y1 - 2, 4):
        arr[y:y + 2, x0 + 4:x1 - 4] = (235, 220, 165)
    arr[y0 + 2:y1 - 2, cx - 2:cx + 2] = (240, 240, 240)
    return arr


class RoiProtectionAndDriftTests(unittest.TestCase):
    """Verify structural ROI precedence, Sobel disclosures, internal shift catching, and locks."""

    def test_internal_drift_detects_local_shift_inside_equal_dimensions(self) -> None:
        base = _textured_scene()
        candidate = base.copy()
        # Shift ONLY the interior hardware/logo block (centered around 96,96) by +3 px horizontally
        patch = base[76:116, 76:116].copy()
        candidate[76:116, 76:116] = base[70, 70]
        candidate[76:116, 79:119] = patch

        rois = [
            {
                "id": "zipper-center",
                "kind": "hardware",
                "policy": "preserve",
                "rect": [72, 72, 48, 48],
            }
        ]

        report = screen_internal_drift(base, candidate, rois=rois)
        self.assertEqual(report["overall_verdict"], "FAIL")
        self.assertGreaterEqual(report["max_block_shift_px"], 2.5)
        self.assertGreater(report["blocks_flagged"], 0)
        self.assertEqual(report["roi_reports"][0]["status"], "FAIL_DRIFT")
        self.assertGreaterEqual(report["roi_reports"][0]["candidate_shift_px"], 2.5)
        self.assertFalse(report["semantic_proof"])

        # Protecting ROI routes exact base bytes through compose_regions and verifies lock cleanly
        masks, _ = build_roi_protection_masks(base, rois)
        skin = np.ones((192, 192), dtype=np.float32)
        confidence = np.ones((192, 192), dtype=np.float32)
        master, _ = compose_regions(
            base,
            candidate,
            skin=skin,
            protected=masks["protected"],
            confidence=confidence,
            blend=RegionBlend(skin=1.0, hair=0.0, fabric=0.0, edge_protection=0.0),
        )
        post_report = screen_internal_drift(
            base,
            candidate,
            rois=rois,
            protected=masks["protected"],
            master=master,
        )
        self.assertEqual(post_report["locked_pixel_mismatches"], 0)
        np.testing.assert_array_equal(master[72:120, 72:120], base[72:120, 72:120])

        # Corrupting a protected pixel in master triggers explicit LOCK_VIOLATION
        corrupt_master = master.copy()
        corrupt_master[96, 96, 0] ^= 0xFF
        fail_lock = screen_internal_drift(
            base,
            candidate,
            rois=rois,
            protected=masks["protected"],
            master=corrupt_master,
        )
        self.assertGreater(fail_lock["locked_pixel_mismatches"], 0)
        self.assertEqual(fail_lock["roi_reports"][0]["status"], "LOCK_VIOLATION")
        self.assertEqual(fail_lock["overall_verdict"], "FAIL")

    def test_explicit_override_precedence_and_sobel_heuristic_bounds(self) -> None:
        base = _textured_scene(96, 96)
        existing_protected = np.zeros((96, 96), dtype=np.float32)
        existing_protected[10:20, 10:20] = 1.0  # existing manual lock

        rois = [
            {
                "id": "auto-logo",
                "kind": "logo",
                "policy": "preserve",
                "override": "unlock",  # explicit unlock overrides default preserve
                "rect": [60, 60, 24, 24],
            },
            {
                "id": "skin-to-lock",
                "kind": "skin",
                "policy": "texture_allowed",
                "override": "lock",  # explicit lock overrides texture_allowed
                "rect": [30, 30, 16, 16],
            },
        ]

        masks, receipt = build_roi_protection_masks(
            base,
            rois,
            existing_protected=existing_protected,
            use_sobel_heuristic=True,
            max_sobel_guard=0.60,
        )

        # Existing manual lock untouched
        np.testing.assert_array_equal(masks["protected"][10:20, 10:20], 1.0)
        # Explicit unlock cleared both protected lock and Sobel heuristic inside ROI
        np.testing.assert_array_equal(masks["protected"][60:84, 60:84], 0.0)
        np.testing.assert_array_equal(masks["edge_guard"][60:84, 60:84], 0.0)
        # Explicit lock locked texture_allowed ROI
        np.testing.assert_array_equal(masks["protected"][30:46, 30:46], 1.0)
        # Secondary Sobel heuristic stays < 1.0 and records explicit non-semantic disclaimer
        self.assertLessEqual(float(masks["edge_guard"].max()), 0.6001)
        self.assertFalse(receipt["sobel_is_semantic_proof"])
        self.assertIn("auto-logo", receipt["unlocked_override_ids"])
        self.assertIn("skin-to-lock", receipt["forced_lock_override_ids"])

    def test_uniform_packshot_has_no_false_drift_and_mismatch_size_fails_closed(self) -> None:
        black_bg = np.full((64, 64, 3), 8, dtype=np.uint8)
        report = screen_internal_drift(black_bg, black_bg.copy())
        self.assertEqual(report["overall_verdict"], "PASS")
        self.assertEqual(report["blocks_flagged"], 0)

        smaller = np.full((32, 32, 3), 8, dtype=np.uint8)
        with self.assertRaises(ValueError):
            screen_internal_drift(black_bg, smaller)

        with self.assertRaises(ValueError):
            validate_rois(
                [{"id": "bad", "kind": "logo", "policy": "preserve", "rect": [50, 10, 30, 10]}],
                (64, 64),
            )

    def test_cli_screen_roi_drift_end_to_end(self) -> None:
        base = _textured_scene(128, 128)
        candidate = base.copy()
        patch = base[48:80, 48:80].copy()
        candidate[48:80, 48:80] = base[20, 20]
        candidate[48:80, 51:83] = patch

        rois = [{"id": "badge", "kind": "logo", "policy": "preserve", "rect": [44, 44, 44, 44]}]

        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            base_p = tmp / "base.png"
            cand_p = tmp / "cand.png"
            rois_p = tmp / "rois.json"
            npz_p = tmp / "masks.npz"
            rep_p = tmp / "report.json"

            Image.fromarray(base, mode="RGB").save(base_p)
            Image.fromarray(candidate, mode="RGB").save(cand_p)
            rois_p.write_text(json.dumps(rois), encoding="utf-8")

            proc_fail = subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / "scripts" / "screen-roi-drift.py"),
                    "--base",
                    str(base_p),
                    "--candidate",
                    str(cand_p),
                    "--rois-json",
                    str(rois_p),
                    "--out-masks-npz",
                    str(npz_p),
                    "--json-report",
                    str(rep_p),
                    "--fail-on-drift",
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc_fail.returncode, 1)
            self.assertTrue(npz_p.is_file())
            self.assertTrue(rep_p.is_file())
            rep_data = json.loads(rep_p.read_text(encoding="utf-8"))
            self.assertEqual(rep_data["drift_screening"]["overall_verdict"], "FAIL")

            # Clean pass exits 0
            proc_pass = subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / "scripts" / "screen-roi-drift.py"),
                    "--base",
                    str(base_p),
                    "--candidate",
                    str(base_p),
                    "--rois-json",
                    str(rois_p),
                    "--fail-on-drift",
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            pass_data = json.loads(proc_pass.stdout)
            self.assertEqual(pass_data["drift_screening"]["overall_verdict"], "PASS")


if __name__ == "__main__":
    unittest.main()
