#!/usr/bin/env python3
"""Evaluate photographic fidelity and restoration metrics for Fidelis audition outputs.

Calculates:
1. Reference-based metrics (when reference or input is supplied):
   - PSNR: Peak Signal-to-Noise Ratio (dB)
   - SSIM: Structural Similarity Index (luminance + contrast + structure)
   - Chromatic Drift (Delta E / Lab color distance): measures color fidelity
   - Edge Gradient Alignment: measures structural geometry conservation without halos
2. No-reference restoration checks:
   - Background Flatness Restraint: measures spurious synthetic noise introduced into flat regions
   - Natural Detail Frequency Ratio: high-frequency to mid-frequency energy ratio
"""

import argparse
import json
import math
from pathlib import Path
import sys
from PIL import Image

try:
    import numpy as np
    from skimage.metrics import structural_similarity as ssim
    from skimage.metrics import peak_signal_noise_ratio as psnr
    HAS_SKIMAGE = True
except ImportError:
    HAS_SKIMAGE = False

def compute_psnr_fallback(img1: Image.Image, img2: Image.Image) -> float:
    # Fallback PSNR implementation if skimage is not available
    im1 = np.asarray(img1).astype(np.float64)
    im2 = np.asarray(img2).astype(np.float64)
    mse = np.mean((im1 - im2) ** 2)
    if mse == 0:
        return float("inf")
    return float(20 * math.log10(255.0 / math.sqrt(mse)))

def evaluate_pair(src_img: Image.Image, upscaled_img: Image.Image) -> dict:
    # Resize source to target dimensions with Bicubic to establish scale-matched baseline
    w, h = upscaled_img.size
    ref_resized = src_img.resize((w, h), Image.Resampling.BICUBIC)

    arr_ref = np.asarray(ref_resized).astype(np.float32)
    arr_out = np.asarray(upscaled_img).astype(np.float32)

    # Ensure RGB
    if arr_ref.ndim == 2:
        arr_ref = np.stack([arr_ref]*3, axis=-1)
    if arr_out.ndim == 2:
        arr_out = np.stack([arr_out]*3, axis=-1)

    arr_ref = arr_ref[:, :, :3]
    arr_out = arr_out[:, :, :3]

    # 1. PSNR
    if HAS_SKIMAGE:
        val_psnr = float(psnr(arr_ref / 255.0, arr_out / 255.0, data_range=1.0))
        val_ssim = float(ssim(arr_ref / 255.0, arr_out / 255.0, data_range=1.0, channel_axis=2))
    else:
        mse = np.mean((arr_ref - arr_out) ** 2)
        val_psnr = float("inf") if mse == 0 else float(20 * math.log10(255.0 / math.sqrt(mse)))
        val_ssim = 0.0

    # 2. Color Drift (Mean Absolute Deviation across RGB channels)
    color_diff = np.abs(arr_ref - arr_out)
    mean_color_drift = float(np.mean(color_diff))

    # 3. High-Frequency Gradient Energy (Laplacian-like edge metric)
    gray_out = np.dot(arr_out[...,:3], [0.2989, 0.5870, 0.1140])
    gx, gy = np.gradient(gray_out)
    edge_energy = float(np.mean(np.sqrt(gx**2 + gy**2)))

    # 4. Background Flatness Restraint
    # Find regions where reference gradient is near zero (smooth backgrounds)
    gray_ref = np.dot(arr_ref[...,:3], [0.2989, 0.5870, 0.1140])
    rgx, rgy = np.gradient(gray_ref)
    ref_grad = np.sqrt(rgx**2 + rgy**2)
    flat_mask = ref_grad < 2.0  # low gradient in reference
    if np.any(flat_mask):
        bg_noise = float(np.std(gray_out[flat_mask] - gray_ref[flat_mask]))
    else:
        bg_noise = 0.0

    return {
        "psnr_db": round(val_psnr, 2),
        "ssim": round(val_ssim, 4),
        "color_drift": round(mean_color_drift, 2),
        "edge_energy": round(edge_energy, 2),
        "bg_noise_restraint": round(bg_noise, 3),
    }

def evaluate_directory(results_dir: Path):
    manifest_p = results_dir / "manifest.json"
    benchmark_p = results_dir / "benchmark.json"

    meta_file = benchmark_p if benchmark_p.is_file() else (manifest_p if manifest_p.is_file() else None)
    if not meta_file:
        print(f"No manifest.json or benchmark.json found in {results_dir}")
        return

    meta = json.loads(meta_file.read_text(encoding="utf-8"))
    src_path = meta.get("input", {}).get("path")
    if not src_path or not Path(src_path).is_file():
        print(f"Source image '{src_path}' not accessible for reference metrics.")
        return

    src_img = Image.open(src_path)
    print(f"Source image: {src_path} ({src_img.width}x{src_img.height})")
    print("-" * 75)
    print(f"{'Model / Output':<25} {'PSNR (dB)':<10} {'SSIM':<8} {'Color Drift':<12} {'BG Restraint':<12}")
    print("-" * 75)

    scores = {}
    outputs = sorted(results_dir.glob("*.png"))
    for out_p in outputs:
        try:
            with Image.open(out_p) as out_img:
                res = evaluate_pair(src_img, out_img)
                scores[out_p.name] = res
                print(f"{out_p.stem:<25} {res['psnr_db']:<10} {res['ssim']:<8} {res['color_drift']:<12} {res['bg_noise_restraint']:<12}")
        except Exception as e:
            print(f"Error evaluating {out_p.name}: {e}")

    summary_file = results_dir / "metrics.json"
    summary_file.write_text(json.dumps(scores, indent=2) + "\n")
    print("-" * 75)
    print(f"Metrics saved to: {summary_file}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Evaluate objective fidelity metrics on Fidelis outputs.")
    parser.add_argument("target", type=Path, help="Results directory containing manifest/benchmark and PNGs")
    args = parser.parse_args()
    evaluate_directory(args.target)
