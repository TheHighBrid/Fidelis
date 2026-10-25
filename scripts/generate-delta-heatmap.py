#!/usr/bin/env python3
"""Visual Hallucination & Drift Delta Heatmap Generator for Fidelis.

Generates high-contrast false-color thermal heatmaps highlighting:
- High-frequency edge shifts and geometry distortions (violating Rule #1)
- Invented artificial grain / texture synthesized in flat areas
- Pixel-level chromatic and luminance drift

Supports standalone image pairs or batch audition directories.
"""

import argparse
import json
from pathlib import Path
import sys
from PIL import Image
import numpy as np
from scipy import ndimage

def get_thermal_lut() -> np.ndarray:
    """Returns a 256x3 RGB lookup table for thermal hallucination visualization."""
    x = np.linspace(0, 1, 256)
    r = np.clip(np.where(x < 0.5, 2.0 * x, 1.0), 0, 1)
    g = np.clip(np.where(x < 0.5, 0.4 * x, 2.0 * (x - 0.5)), 0, 1)
    b = np.clip(np.where(x < 0.25, 4.0 * x, np.where(x < 0.6, 1.0 - 2.5 * (x - 0.25), 2.5 * (x - 0.6))), 0, 1)
    return (np.stack([r, g, b], axis=-1) * 255).astype(np.uint8)

def compute_delta_map(src_img: Image.Image, out_img: Image.Image, overlay: bool = True, alpha: float = 0.6) -> Image.Image:
    w, h = out_img.size
    ref_resized = src_img.resize((w, h), Image.Resampling.LANCZOS)

    ref_gray = np.asarray(ref_resized.convert("L")).astype(np.float32)
    out_gray = np.asarray(out_img.convert("L")).astype(np.float32)

    # 1. Pixel luminance absolute delta
    pixel_delta = np.abs(out_gray - ref_gray)

    # 2. Gradient / high-frequency edge delta
    gx_ref = ndimage.sobel(ref_gray, axis=1)
    gy_ref = ndimage.sobel(ref_gray, axis=0)
    mag_ref = np.sqrt(gx_ref**2 + gy_ref**2)

    gx_out = ndimage.sobel(out_gray, axis=1)
    gy_out = ndimage.sobel(out_gray, axis=0)
    mag_out = np.sqrt(gx_out**2 + gy_out**2)

    grad_delta = np.abs(mag_out - mag_ref)

    # 3. Composite score (balanced between edge shift & texture invention)
    comp_delta = 0.35 * (pixel_delta / 255.0) + 0.65 * (grad_delta / max(np.percentile(mag_ref, 98), 10.0))

    # Normalize with 98.5th percentile scaling to highlight fine drift
    norm_val = np.percentile(comp_delta, 98.5)
    if norm_val <= 1e-4:
        norm_val = 1.0
    scaled = np.clip(comp_delta / norm_val, 0.0, 1.0)
    indices = (scaled * 255).astype(np.uint8)

    # Apply thermal LUT
    lut = get_thermal_lut()
    heatmap_rgb = lut[indices] # shape (H, W, 3)

    if overlay:
        # Desaturate reference to subtle background
        ref_mono = np.stack([ref_gray, ref_gray, ref_gray], axis=-1).astype(np.float32) * 0.4
        blended = np.clip(ref_mono * (1.0 - alpha) + heatmap_rgb.astype(np.float32) * alpha, 0, 255).astype(np.uint8)
        return Image.fromarray(blended)
    else:
        return Image.fromarray(heatmap_rgb)

def process_directory(audition_dir: Path, overlay: bool = True):
    manifest_p = audition_dir / "manifest.json"
    if not manifest_p.is_file():
        print(f"error: manifest.json not found in {audition_dir}", file=sys.stderr)
        sys.exit(1)

    manifest = json.loads(manifest_p.read_text(encoding="utf-8"))
    src_path = manifest.get("input", {}).get("path")
    if not src_path or not Path(src_path).is_file():
        print(f"error: source image '{src_path}' not found", file=sys.stderr)
        sys.exit(1)

    src_img = Image.open(src_path)
    entries = manifest.get("models") or manifest.get("entries") or []
    count = 0

    for entry in entries:
        m_name = entry.get("model", {}).get("name", "model")
        fn = entry.get("output", {}).get("filename", f"{m_name}.png")
        out_p = audition_dir / fn
        if not out_p.is_file():
            continue

        with Image.open(out_p) as out_im:
            heatmap = compute_delta_map(src_img, out_im, overlay=overlay)
            heatmap_path = audition_dir / f"{Path(fn).stem}_heatmap.png"
            heatmap.save(heatmap_path)
            print(f"  Generated heatmap: {heatmap_path.name}")
            count += 1

    print(f"\nCompleted: {count} delta heatmap(s) generated in {audition_dir}")

def main():
    parser = argparse.ArgumentParser(description="Generate visual hallucination and drift delta heatmaps.")
    parser.add_argument("source", type=Path, help="Source image (or audition directory)")
    parser.add_argument("upscaled", type=Path, nargs="?", help="Upscaled image (if evaluating single pair)")
    parser.add_argument("-o", "--output", type=Path, help="Output heatmap path (for single pair)")
    parser.add_argument("--no-overlay", action="store_true", help="Generate pure false-color heatmap without image overlay")
    parser.add_argument("--alpha", type=float, default=0.65, help="Overlay blend weight (default: 0.65)")
    args = parser.parse_args()

    if args.source.is_dir():
        process_directory(args.source, overlay=not args.no_overlay)
    elif args.upscaled and args.source.is_file() and args.upscaled.is_file():
        out_dest = args.output or Path(f"{args.upscaled.stem}_heatmap.png")
        with Image.open(args.source) as sim, Image.open(args.upscaled) as uim:
            hm = compute_delta_map(sim, uim, overlay=not args.no_overlay, alpha=args.alpha)
            hm.save(out_dest)
            print(f"Delta heatmap saved to: {out_dest}")
    else:
        parser.print_help()
        sys.exit(2)

if __name__ == "__main__":
    main()
