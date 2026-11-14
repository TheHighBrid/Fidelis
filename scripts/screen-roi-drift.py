#!/usr/bin/env python3
"""Screen structural ROIs and internal spatial drift on aligned sRGB passes (F10 / MEL-64)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Dict, List

import numpy as np
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from fidelis.postprocess.roi_protection import (  # noqa: E402
    build_roi_protection_masks,
    screen_internal_drift,
)


def _load_rgb_png(path: Path) -> np.ndarray:
    with Image.open(path) as im:
        if im.mode != "RGB":
            raise ValueError(f"{path}: expected uint8 RGB image, found mode {im.mode}")
        return np.array(im, dtype=np.uint8)


def _load_rois(path: Path | None) -> List[Dict[str, Any]]:
    if path is None:
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict) and isinstance(raw.get("rois"), list):
        return raw["rois"]
    raise ValueError("ROI JSON must be a list of ROIs or an object containing a 'rois' list")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, required=True, help="Precision base RGB image")
    parser.add_argument("--candidate", type=Path, required=True, help="Aligned candidate texture RGB image")
    parser.add_argument("--master", type=Path, default=None, help="Optional composed master RGB image for lock checks")
    parser.add_argument("--rois-json", type=Path, default=None, help="Optional JSON file containing explicit ROIs")
    parser.add_argument("--sobel-heuristic", action="store_true", help="Enable secondary Sobel edge_guard attenuation")
    parser.add_argument("--out-masks-npz", type=Path, default=None, help="Optional output NPZ (protected, edge_guard, drift_guard)")
    parser.add_argument("--json-report", type=Path, default=None, help="Optional JSON path for screening report")
    parser.add_argument("--fail-on-drift", action="store_true", help="Exit non-zero whenever overall_verdict == FAIL")
    args = parser.parse_args()

    try:
        base = _load_rgb_png(args.base.resolve())
        candidate = _load_rgb_png(args.candidate.resolve())
        master = _load_rgb_png(args.master.resolve()) if args.master is not None else None
        rois = _load_rois(args.rois_json.resolve() if args.rois_json is not None else None)

        masks, mask_receipt = build_roi_protection_masks(
            base,
            rois,
            use_sobel_heuristic=args.sobel_heuristic,
        )
        drift_report = screen_internal_drift(
            base,
            candidate,
            rois=rois,
            protected=masks["protected"],
            master=master,
        )
        drift_guard = drift_report.pop("drift_guard_mask")

        if args.out_masks_npz is not None:
            args.out_masks_npz.parent.mkdir(parents=True, exist_ok=True)
            np.savez_compressed(
                args.out_masks_npz,
                protected=masks["protected"],
                edge_guard=masks["edge_guard"],
                drift_guard=drift_guard,
            )

        payload = {
            "mask_receipt": mask_receipt,
            "drift_screening": drift_report,
        }
        if args.json_report is not None:
            args.json_report.parent.mkdir(parents=True, exist_ok=True)
            args.json_report.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

        print(json.dumps(payload, indent=2))
        if drift_report["locked_pixel_mismatches"] > 0:
            return 1
        if any(r["status"] == "LOCK_VIOLATION" for r in drift_report["roi_reports"]):
            return 1
        if args.fail_on_drift and drift_report["overall_verdict"] == "FAIL":
            return 1
        return 0
    except (OSError, ValueError) as exc:
        print(f"ROI/drift screening error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
