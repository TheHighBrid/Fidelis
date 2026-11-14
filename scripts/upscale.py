#!/usr/bin/env python3
"""CLI utility for instrumented upscaling with span tracing and unsigned provenance records."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

# Ensure repository root is in sys.path
repo_root = Path(__file__).resolve().parents[1]
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from fidelis.core.pipeline import UpscalePipeline


def main():
    parser = argparse.ArgumentParser(description="Instrumented Fidelis upscaling pipeline with span telemetry and unsigned execution records.")
    parser.add_argument("input", type=Path, help="Input image file")
    parser.add_argument("output", type=Path, help="Output image file")
    parser.add_argument("-m", "--model", default="Smart_Balanced", help="Model profile (realesrgan-x4plus, d2fk-v1, gfpgan_face, etc.)")
    parser.add_argument("-t", "--tile-size", type=int, default=512, help="Tile size in pixels (default: 512)")
    parser.add_argument("--overlap", type=int, default=32, help="Tile overlap in pixels (default: 32)")
    parser.add_argument("--scale", type=int, default=4, help="Scale factor (default: 4)")
    parser.add_argument("--no-tiling", action="store_true", help="Disable tiled decomposition")
    parser.add_argument("--portrait", action="store_true", help="Force facial identity pore restoration")
    parser.add_argument("-w", "--fidelity-w", type=float, default=0.70, help="Face fidelity balance w [0.0-1.0]")
    parser.add_argument("--no-text", action="store_true", help="Disable text glyph restoration")
    parser.add_argument("--color-fix", default="auto", choices=["auto", "wavelet", "adain", "none"], help="Color drift fix")
    parser.add_argument("--telemetry-url", help="Target URL for telemetry posting (default: http://127.0.0.1:8011/api/telemetry/trace?project=fidelis)")
    parser.add_argument("--no-telemetry", action="store_true", help="Disable posting telemetry to kernel endpoint")
    parser.add_argument("--json-manifest", type=Path, help="Optional destination path for JSON telemetry manifest")

    parser.add_argument("--ground-truth", type=Path, help="Aligned reference at native output dimensions; no automatic resize")
    args = parser.parse_args()

    pipeline = UpscalePipeline()
    res = pipeline.run(
        input_path=args.input,
        output_path=args.output,
        model_profile=args.model,
        scale=args.scale,
        tile_size=args.tile_size,
        overlap=args.overlap,
        tiled=not args.no_tiling,
        portrait=True if args.portrait else None,
        fidelity_w=args.fidelity_w,
        text_preserve=not args.no_text,
        color_fix=args.color_fix,
        post_telemetry=not args.no_telemetry,
        telemetry_endpoint=args.telemetry_url,
        ground_truth_path=args.ground_truth,
    )

    print(f"\n=======================================================")
    print(f" Fidelis Instrumented Upscaling Completed")
    print(f"=======================================================")
    print(f"Input:        {res.input_path} ({res.input_dimensions[0]}x{res.input_dimensions[1]}, {res.input_format})")
    print(f"Noise Level:  {res.input_noise_level:.2f} (MAD wavelet variance)")
    print(f"Profile:      {res.model_profile} (Engine: {res.actual_model})")
    print(f"Tile Size:    {res.tile_size}px (Overlap: {res.overlap}px, Strategy: {res.tile_execution.get('tile_strategy', 'direct')})")
    print(f"Peak VRAM:    {res.vram_peak_mb:.1f} MB")
    print(f"Speed:        {res.processing_time_per_megapixel_ms:.1f} ms/MP ({res.megapixels} MP in {res.elapsed_ms}ms)")
    def measurement(name, digits):
        value = res.metrics.get(name)
        return "unavailable" if value is None else f"{value:.{digits}f}"
    print(f"Metric ref:   {res.metric_context.get('reference', 'unavailable')} ({res.metric_context.get('status', 'unavailable')})")
    print(f"PSNR / SSIM:  {measurement('psnr', 2)} / {measurement('ssim', 4)}")
    print(f"Gradient distance proxy: {measurement('gradient_distance_proxy', 3)}; LPIPS: unavailable")
    print(f"Artifacts:    {', '.join(res.detected_artifacts) if res.detected_artifacts else 'None detected'}")
    print(f"Output:       {res.output_path} ({res.output_dimensions[0]}x{res.output_dimensions[1]})")
    print(f"SHA-256:      {res.output_sha256}")
    print(f"Provenance:   {res.c2pa_status.upper()}")
    print(f"EXIF:         {'Preserved' if res.exif_preserved else 'Not Present/Skipped'}")
    print(f"Telemetry:    {'POSTED (Status: ' + str(res.telemetry_response.get('status')) + ')' if res.telemetry_posted else ('Attempted (' + str(res.telemetry_response.get('status')) + ')' if res.telemetry_response else 'Disabled')}")
    print(f"Spans Traced: {len(res.spans)}")
    print(f"=======================================================\n")

    if args.json_manifest:
        args.json_manifest.parent.mkdir(parents=True, exist_ok=True)
        with open(args.json_manifest, "w", encoding="utf-8") as f:
            json.dump(res.to_dict(), f, indent=2)
        print(f"Manifest written to: {args.json_manifest}")


if __name__ == "__main__":
    main()
