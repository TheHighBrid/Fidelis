#!/usr/bin/env python3
"""Opt-in local product upscale with source-derived edge and exact ROI locks."""

import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile

import numpy as np
from PIL import Image
from scipy import ndimage

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fidelis.postprocess.regions import RegionBlend, compose_regions
from fidelis.postprocess.roi_protection import build_roi_protection_masks, validate_rois
from fidelis.studio.png import read_rgb8_png

MAX_OUTPUT_PIXELS = 8_000_000
SCALE = 4


def texture_confidence(base_gray, candidate):
    """Reduce the model contribution where it erases source-aligned texture."""
    candidate_gray = np.asarray(Image.fromarray(candidate).convert("L"), dtype=np.float32)
    base_detail = base_gray - ndimage.gaussian_filter(base_gray, 2)
    candidate_detail = candidate_gray - ndimage.gaussian_filter(candidate_gray, 2)
    source_energy = ndimage.uniform_filter(base_detail * base_detail, size=17)
    retained = ndimage.uniform_filter(base_detail * candidate_detail, size=17)
    ratio = retained / np.maximum(source_energy, 0.25)
    # Flat areas carry too little evidence for a meaningful comparison.
    confidence = np.where(source_energy >= 0.25, np.clip((ratio - 0.85) / 0.15, 0, 1), 1)
    return ndimage.gaussian_filter(confidence, 3)


def compose_product(base, candidate, rois):
    if base.shape != candidate.shape:
        raise ValueError("Product passes must have identical dimensions")
    masks, _ = build_roi_protection_masks(base, rois)
    gray = np.asarray(Image.fromarray(base).convert("L"), dtype=np.float32)
    edges = np.hypot(ndimage.sobel(gray, axis=0), ndimage.sobel(gray, axis=1))
    locked = ndimage.binary_dilation(edges > max(np.percentile(edges, 85), 15), iterations=6)
    texture_weight = texture_confidence(gray, candidate)
    for roi in rois:
        if roi["override"] == "unlock":
            x, y, w, h = roi["rect"]
            locked[y:y + h, x:x + w] = False
            texture_weight[y:y + h, x:x + w] = 1
    locked |= masks["protected"] == 1
    confidence = (
        np.clip(ndimage.distance_transform_edt(~locked) / 8, 0, 1).astype(np.float32)
        if locked.any() else np.ones(locked.shape, dtype=np.float32)
    )
    confidence *= texture_weight
    result = np.empty_like(base)
    for start in range(0, base.shape[0], 128):
        rows = slice(start, start + 128)
        result[rows], _ = compose_regions(
            base[rows], candidate[rows],
            fabric=np.ones_like(confidence[rows]), confidence=confidence[rows],
            blend=RegionBlend(fabric=1),
        )
    return result, locked


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--model", default="RealeSR-general-v3")
    parser.add_argument("--rois-json", type=Path, help="ROI list in input-image pixels")
    args = parser.parse_args()
    try:
        if args.output.suffix.lower() != ".png" or args.output.resolve() == args.source.resolve():
            raise ValueError("Output must be a separate PNG")
        with args.source.open("rb") as stream:
            source = read_rgb8_png(stream, max_pixels=MAX_OUTPUT_PIXELS // SCALE**2)
        rois = validate_rois(json.loads(args.rois_json.read_text()) if args.rois_json else [], source.shape[:2])
        for roi in rois:
            roi["rect"] = [v * SCALE for v in roi["rect"]]
        size = (source.shape[1] * SCALE, source.shape[0] * SCALE)
        base = np.asarray(Image.fromarray(source).resize(size, Image.Resampling.BICUBIC))
        with tempfile.TemporaryDirectory(prefix="fidelis-product-", dir=args.output.parent) as tmp:
            staged = Path(tmp)
            source_path = staged / "source.png"
            candidate_path = staged / "candidate.png"
            Image.fromarray(source).save(source_path)
            subprocess.run(
                [str(ROOT / "bin/fidelis"), "upscale", str(source_path),
                 str(candidate_path), "--model", args.model], check=True,
            )
            with candidate_path.open("rb") as stream:
                candidate = read_rgb8_png(stream, max_pixels=MAX_OUTPUT_PIXELS, expected_size=size)
            result, locked = compose_product(base, candidate, rois)
            final = staged / "protected.png"
            Image.fromarray(result).save(final)
            final.replace(args.output)
        print(json.dumps({"output": str(args.output), "model": args.model,
                          "locked_pixels": int(locked.sum()), "dimensions": size}))
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"Product upscale failed: {error}\n")


if __name__ == "__main__":
    main()
