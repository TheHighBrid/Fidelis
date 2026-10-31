#!/usr/bin/env python3
"""Seamless tiled upscaling with cosine overlap blending for ultra-high-resolution images.

Eliminates VRAM exhaustion on mobile GPUs and prevents grid-line seams on subtle
skin tone and fabric gradients.
"""

import argparse
import math
from pathlib import Path
import shutil
import subprocess
import tempfile
from PIL import Image
import numpy as np

def make_cosine_window(
    h: int,
    w: int,
    overlap_y: int,
    overlap_x: int,
    fade_top: bool = True,
    fade_bottom: bool = True,
    fade_left: bool = True,
    fade_right: bool = True,
) -> np.ndarray:
    """Cosine feathering with strictly positive weights and protected outer edges."""
    def ramp(length, edge, fade_start, fade_end):
        if length < 1:
            raise ValueError("Tile dimensions must be positive")
        r = np.ones(length, dtype=np.float32)
        edge = min(max(edge, 0), length)
        if edge:
            # Interior samples avoid zero-weight pixels when tiles meet a canvas edge.
            t = np.linspace(0, math.pi / 2, edge + 2, dtype=np.float32)[1:-1]
            sin_ramp = np.sin(t) ** 2
            if fade_start:
                r[:edge] = np.minimum(r[:edge], sin_ramp)
            if fade_end:
                r[-edge:] = np.minimum(r[-edge:], sin_ramp[::-1])
        return r

    wy = ramp(h, overlap_y, fade_top, fade_bottom)
    wx = ramp(w, overlap_x, fade_left, fade_right)
    return np.outer(wy, wx)

def tiled_upscale(
    input_path: Path,
    output_path: Path,
    model: str = "RealeSR-general-v3",
    tile_size: int = 512,
    overlap: int = 32,
    scale: int = 4,
    cli_path: str = None
):
    if tile_size < 1 or overlap < 0 or overlap >= tile_size:
        raise ValueError("tile_size must be positive and overlap must be smaller than tile_size")
    # The installed NCNN runtime and CLI are explicitly 4x only.
    if scale != 4:
        raise ValueError("The current Fidelis NCNN runtime supports scale=4 only")
    if not cli_path:
        cli_path = shutil.which("fidelis") or "bin/fidelis"

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with Image.open(input_path) as im:
        src = im.convert("RGB")
        w_in, h_in = src.size

    # If image fits inside one tile, process directly
    if w_in <= tile_size and h_in <= tile_size:
        print(f"Image {w_in}x{h_in} fits within tile size ({tile_size}px); running direct upscale...")
        cmd = [cli_path, "upscale", str(input_path), str(output_path), "--model", model]
        subprocess.check_call(cmd)
        with Image.open(output_path) as upscaled:
            if upscaled.size != (w_in * scale, h_in * scale):
                raise ValueError("Direct model output dimensions do not match the 4x contract")
        return

    w_out = w_in * scale
    h_out = h_in * scale
    out_accum = np.zeros((h_out, w_out, 3), dtype=np.float32)
    weight_accum = np.zeros((h_out, w_out), dtype=np.float32)

    step = tile_size - overlap
    x_starts = list(range(0, max(1, w_in - tile_size), step))
    if not x_starts or x_starts[-1] + tile_size < w_in:
        x_starts.append(max(0, w_in - tile_size))

    y_starts = list(range(0, max(1, h_in - tile_size), step))
    if not y_starts or y_starts[-1] + tile_size < h_in:
        y_starts.append(max(0, h_in - tile_size))

    total_tiles = len(x_starts) * len(y_starts)
    print(f"Tiled upscale: {w_in}x{h_in} -> {w_out}x{h_out} via {total_tiles} tile(s) (size={tile_size}, overlap={overlap}, model={model})...")

    with tempfile.TemporaryDirectory(prefix="fidelis_tile_") as tmp_dir:
        tmp = Path(tmp_dir)
        tile_in = tmp / "tile_in.png"
        tile_out = tmp / "tile_out.png"

        idx = 0
        for y0 in y_starts:
            for x0 in x_starts:
                idx += 1
                box = (x0, y0, min(w_in, x0 + tile_size), min(h_in, y0 + tile_size))
                tile_crop = src.crop(box)
                tw, th = tile_crop.size

                tile_crop.save(tile_in)
                tile_out.unlink(missing_ok=True)

                cmd = [cli_path, "upscale", str(tile_in), str(tile_out), "--model", model]
                subprocess.check_call(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

                out_tw, out_th = tw * scale, th * scale
                with Image.open(tile_out) as im_up:
                    if im_up.size != (out_tw, out_th):
                        raise ValueError(
                            f"Tile {idx} returned {im_up.size}, expected {(out_tw, out_th)}"
                        )
                    tile_arr = np.asarray(im_up.convert("RGB")).astype(np.float32)

                window = make_cosine_window(
                    out_th, out_tw, overlap * scale, overlap * scale,
                    fade_top=y0 > 0,
                    fade_bottom=y0 + th < h_in,
                    fade_left=x0 > 0,
                    fade_right=x0 + tw < w_in,
                )

                x_out = x0 * scale
                y_out = y0 * scale

                out_accum[y_out:y_out + out_th, x_out:x_out + out_tw] += tile_arr * window[:, :, np.newaxis]
                weight_accum[y_out:y_out + out_th, x_out:x_out + out_tw] += window

                print(f"  Processed tile [{idx}/{total_tiles}] at ({x0},{y0})", end="\r", flush=True)

    print()
    if np.any(weight_accum <= 0):
        raise RuntimeError("Tiled upscaling left uncovered output pixels")
    final_arr = np.clip(
        out_accum / weight_accum[:, :, np.newaxis] + 0.5, 0, 255
    ).astype(np.uint8)

    final_img = Image.fromarray(final_arr)
    final_img.save(output_path)
    print(f"Seamless tiled image written: {output_path} ({w_out}x{h_out}, {output_path.stat().st_size:,} bytes)")

def main():
    parser = argparse.ArgumentParser(description="Seamless tiled upscale with cosine blending for large fashion photography.")
    parser.add_argument("input", type=Path, help="Input image file")
    parser.add_argument("output", type=Path, help="Output destination image file")
    parser.add_argument("-m", "--model", default="RealeSR-general-v3", help="Model name (default: RealeSR-general-v3)")
    parser.add_argument("-t", "--tile-size", type=int, default=512, help="Tile size in pixels (default: 512)")
    parser.add_argument("--overlap", type=int, default=32, help="Overlap margin in pixels (default: 32)")
    parser.add_argument("--scale", type=int, default=4, help="Scale factor (default: 4)")
    args = parser.parse_args()

    tiled_upscale(
        args.input,
        args.output,
        model=args.model,
        tile_size=args.tile_size,
        overlap=args.overlap,
        scale=args.scale
    )

if __name__ == "__main__":
    main()
