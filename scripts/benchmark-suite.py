#!/usr/bin/env python3
"""CLI utility to evaluate super-resolution outputs across the 5-dimension quality benchmark."""

import argparse
import json
import sys
from pathlib import Path
import cv2

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from fidelis.eval.benchmark_suite import BenchmarkSuite


def main():
    parser = argparse.ArgumentParser(description="Evaluate super-resolved outputs across the 5-dimension quality benchmark.")
    parser.add_argument("source", help="Path to original input or reference ground-truth image")
    parser.add_argument("upscaled", help="Path to super-resolved output image")
    parser.add_argument("--json", action="store_true", help="Output machine-readable JSON")
    args = parser.parse_args()

    src_p = Path(args.source)
    up_p = Path(args.upscaled)

    if not src_p.is_file() or not up_p.is_file():
        print(f"Error: image files not found ({src_p}, {up_p})", file=sys.stderr)
        sys.exit(1)

    src_bgr = cv2.imread(str(src_p))
    up_bgr = cv2.imread(str(up_p))

    src_rgb = cv2.cvtColor(src_bgr, cv2.COLOR_BGR2RGB)
    up_rgb = cv2.cvtColor(up_bgr, cv2.COLOR_BGR2RGB)

    suite = BenchmarkSuite()
    report = suite.evaluate_pair(src_rgb, up_rgb)

    if args.json:
        data = {
            "source": str(src_p),
            "upscaled": str(up_p),
            "psnr_db": report.psnr_db,
            "ssim": report.ssim,
            "color_drift_delta_e": report.color_drift_delta_e,
            "luminance_drift": report.luminance_drift,
            "edge_energy_gain": report.edge_energy_gain,
            "gradient_coherence_pct": report.gradient_coherence_pct,
            "hallucination_risk": report.hallucination_risk,
            "quality_verdict": report.quality_verdict
        }
        print(json.dumps(data, indent=2))
        return

    print("=======================================================")
    print(" Fidelis 5-Dimension Super-Resolution Quality Benchmark")
    print("=======================================================")
    print(f"Source:              {src_p}")
    print(f"Upscaled:            {up_p}")
    print("-------------------------------------------------------")
    print(f"1. Structural Fidelity:")
    print(f"   • PSNR:           {report.psnr_db} dB")
    print(f"   • SSIM:           {report.ssim}")
    print(f"2. Color Stabilization:")
    print(f"   • CIELAB Delta E: {report.color_drift_delta_e} (target < 3.5)")
    print(f"   • Lum Drift:      {report.luminance_drift}")
    print(f"3. Perceptual Coherence:")
    print(f"   • Gradient Match: {report.gradient_coherence_pct}% (target >= 85%)")
    print(f"   • Edge Energy:    {report.edge_energy_gain}x")
    print(f"4. Hallucination Risk: {report.hallucination_risk}")
    print(f"5. Quality Verdict:    [{report.quality_verdict}]")
    print("=======================================================")


if __name__ == "__main__":
    main()
