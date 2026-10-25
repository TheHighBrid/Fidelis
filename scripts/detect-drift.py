#!/usr/bin/env python3
"""Geometric and Identity Drift Detector for Fidelis image restoration.

Enforces Fidelis Quality Rule #1:
'Faces, hands, body proportions, garment construction, seams, logos and hardware must not drift.'

Calculates:
1. Max & Mean Structural Edge Displacement (pixels relative to native resolution)
2. Gradient Direction Coherence (% of edge tangents preserving source orientation)
3. Hallucinated Edge Ratio (% of high-frequency contours invented from flat regions)
4. Overall Status: PASS, WARN, or FAIL (DRIFT DETECTED)
"""

import argparse
import json
import math
from pathlib import Path
import sys
from PIL import Image
import numpy as np
from scipy import ndimage

def compute_drift(src_img: Image.Image, upscaled_img: Image.Image) -> dict:
    w_out, h_out = upscaled_img.size
    ref_resized = src_img.resize((w_out, h_out), Image.Resampling.BICUBIC)

    # Convert to luminance
    arr_ref = np.asarray(ref_resized.convert("L")).astype(np.float32)
    arr_out = np.asarray(upscaled_img.convert("L")).astype(np.float32)

    # 1. Gradient fields (Sobel)
    gx_ref = ndimage.sobel(arr_ref, axis=1)
    gy_ref = ndimage.sobel(arr_ref, axis=0)
    mag_ref = np.sqrt(gx_ref**2 + gy_ref**2)

    gx_out = ndimage.sobel(arr_out, axis=1)
    gy_out = ndimage.sobel(arr_out, axis=0)
    mag_out = np.sqrt(gx_out**2 + gy_out**2)

    # High-contrast edge mask in reference (seams, logos, facial contours)
    threshold = np.percentile(mag_ref, 85)
    edge_mask = mag_ref > max(threshold, 15.0)

    if not np.any(edge_mask):
        return {
            "mean_edge_shift_px": 0.0,
            "max_edge_shift_px": 0.0,
            "gradient_coherence_pct": 100.0,
            "hallucinated_edge_pct": 0.0,
            "status": "PASS"
        }

    # 2. Gradient Direction Coherence
    # Cosine similarity between reference and output gradient vectors on true edges
    dot_prod = (gx_ref * gx_out + gy_ref * gy_out)
    norm_prod = (mag_ref * mag_out) + 1e-6
    cos_sim = dot_prod / norm_prod
    valid_cos = cos_sim[edge_mask]
    coherence = float(np.mean(np.clip(valid_cos, 0.0, 1.0)) * 100.0)

    # 3. Structural Edge Displacement (Distance Transform)
    # Binary edge map of output
    out_edge_mask = mag_out > max(threshold * 0.8, 12.0)
    dist_map = ndimage.distance_transform_edt(~out_edge_mask)

    shifts_on_ref_edges = dist_map[edge_mask]
    mean_shift = float(np.mean(shifts_on_ref_edges))
    max_shift = float(np.percentile(shifts_on_ref_edges, 98))

    # 4. Hallucinated Edge Ratio
    # Output edges located where source was completely flat (mag_ref < 5.0)
    flat_ref_mask = mag_ref < 5.0
    if np.any(flat_ref_mask):
        hallucinated_pixels = np.sum(out_edge_mask & flat_ref_mask)
        total_flat_pixels = np.sum(flat_ref_mask)
        hallucination_pct = float((hallucinated_pixels / total_flat_pixels) * 100.0)
    else:
        hallucination_pct = 0.0

    # 5. Verdict
    # If mean shift > 2.0px or coherence < 80%: FAIL
    if mean_shift > 2.5 or coherence < 78.0 or hallucination_pct > 5.0:
        status = "FAIL (DRIFT DETECTED)"
    elif mean_shift > 1.2 or coherence < 88.0 or hallucination_pct > 2.0:
        status = "WARN (MINOR DRIFT)"
    else:
        status = "PASS (STABLE)"

    return {
        "mean_edge_shift_px": round(mean_shift, 2),
        "max_edge_shift_px": round(max_shift, 2),
        "gradient_coherence_pct": round(coherence, 1),
        "hallucinated_edge_pct": round(hallucination_pct, 2),
        "status": status
    }

def analyze_directory(audition_dir: Path, strict: bool = False):
    manifest_p = audition_dir / "manifest.json"
    if not manifest_p.is_file():
        print(f"Error: manifest.json not found in {audition_dir}", file=sys.stderr)
        sys.exit(1)

    manifest = json.loads(manifest_p.read_text(encoding="utf-8"))
    src_path = manifest.get("input", {}).get("path")
    if not src_path or not Path(src_path).is_file():
        print(f"Error: input source image '{src_path}' not found.", file=sys.stderr)
        sys.exit(1)

    src_img = Image.open(src_path)
    print(f"\n===========================================================================")
    print(f" Fidelis Geometric & Identity Drift Analysis")
    print(f" Source: {Path(src_path).name} ({src_img.width}x{src_img.height})")
    print(f"===========================================================================")
    print(f"{'Model':<22} {'Mean Shift':<12} {'Max Shift':<12} {'Coherence':<12} {'Status':<16}")
    print("-" * 75)

    reports = {}
    has_failure = False

    models_list = manifest.get("models") or manifest.get("entries") or []
    for entry in models_list:
        m_name = entry.get("model", {}).get("name", "Unknown")
        fn = entry.get("output", {}).get("filename", "")
        img_p = audition_dir / fn
        if not img_p.is_file():
            continue

        with Image.open(img_p) as out_im:
            res = compute_drift(src_img, out_im)
            reports[m_name] = res
            status_str = res["status"]
            if "FAIL" in status_str:
                has_failure = True
            print(f"{m_name:<22} {res['mean_edge_shift_px']:<4} px     {res['max_edge_shift_px']:<4} px     {res['gradient_coherence_pct']:<5}%      {status_str}")

    drift_json = audition_dir / "drift_analysis.json"
    drift_json.write_text(json.dumps(reports, indent=2) + "\n")
    print("-" * 75)
    print(f"Analysis saved: {drift_json}")

    if strict and has_failure:
        print("\nStrict mode: Geometric/identity drift detected in candidate model(s)!", file=sys.stderr)
        sys.exit(1)

def main():
    parser = argparse.ArgumentParser(description="Analyze geometric and identity drift for Fidelis models.")
    parser.add_argument("target", type=Path, help="Audition directory (or source image if --output supplied)")
    parser.add_argument("-o", "--output", type=Path, help="Upscaled image (for single pair evaluation)")
    parser.add_argument("--strict", action="store_true", help="Exit with error if any candidate fails drift check")
    args = parser.parse_args()

    if args.target.is_dir():
        analyze_directory(args.target, strict=args.strict)
    elif args.output and args.target.is_file() and args.output.is_file():
        with Image.open(args.target) as sim, Image.open(args.output) as oim:
            res = compute_drift(sim, oim)
            print(json.dumps(res, indent=2))
            if args.strict and "FAIL" in res["status"]:
                sys.exit(1)
    else:
        parser.print_help()
        sys.exit(2)

if __name__ == "__main__":
    main()
