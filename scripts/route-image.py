#!/usr/bin/env python3
"""CLI utility to profile an image and execute smart degradation routing."""

import argparse
import json
import sys
from pathlib import Path
import cv2

# Add repo root to sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import fidelis
from fidelis.core.router import SmartRouter, UpscaleMode


def main():
    parser = argparse.ArgumentParser(description="Profile image degradation and determine optimal restoration routing.")
    parser.add_argument("image", help="Path to input image file")
    parser.add_argument("--mode", choices=["auto", "faithful", "balanced", "creative", "photo_restore"], default="auto")
    parser.add_argument("--json", action="store_true", help="Output machine-readable JSON")
    args = parser.parse_args()

    img_path = Path(args.image)
    if not img_path.is_file():
        print(f"Error: image not found: {img_path}", file=sys.stderr)
        sys.exit(1)

    img = cv2.imread(str(img_path))
    if img is None:
        print(f"Error: failed to decode image: {img_path}", file=sys.stderr)
        sys.exit(1)

    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    router = SmartRouter()
    decision = router.route(rgb, requested_mode=UpscaleMode(args.mode))

    profile = decision["profile"]

    if args.json:
        data = {
            "image": str(img_path),
            "dimensions": f"{profile.width}x{profile.height}",
            "blur_score": profile.blur_score,
            "noise_variance": profile.noise_variance,
            "jpeg_blockiness": profile.jpeg_blockiness,
            "face_count": profile.face_count,
            "text_count": profile.text_count,
            "is_clean_high_res": profile.is_clean_high_res,
            "mode": decision["mode"],
            "tier": decision["tier"],
            "model": decision["model"],
            "actions": decision["actions"]
        }
        print(json.dumps(data, indent=2))
        return

    print("=======================================================")
    print(" Fidelis Smart Degradation Profiler & Router (v3.2.0)")
    print("=======================================================")
    print(f"Input:           {img_path}")
    print(f"Dimensions:      {profile.width} x {profile.height} px")
    print(f"Blur Score:      {profile.blur_score} (Laplacian variance)")
    print(f"Noise Variance:  {profile.noise_variance} (Wavelet MAD)")
    print(f"JPEG Blockiness: {profile.jpeg_blockiness} (8x8 DCT grid ratio)")
    print(f"Detected ROIs:   {profile.face_count} face(s), {profile.text_count} text block(s)")
    print("-------------------------------------------------------")
    print(f"Routed Mode:     {decision['mode'].upper()} (Tier {decision['tier']})")
    print(f"Target Model:    {decision['model']}")
    print("Action Plan:")
    print(f"  • Face Restoration:  {'Enabled (CodeFormer w=' + str(decision['actions']['face_fidelity_w']) + ')' if decision['actions']['run_face_restoration'] else 'Disabled'}")
    print(f"  • Text Preservation: {'Enabled (Glyph Sharpening)' if decision['actions']['run_text_restoration'] else 'Disabled'}")
    print(f"  • Color Fix:         {decision['actions']['color_correction'].upper()}")
    print("=======================================================")


if __name__ == "__main__":
    main()
