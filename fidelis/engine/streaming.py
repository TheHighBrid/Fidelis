"""Disk-backed row streaming for deterministic SR tile fusion.

Accumulates only one output tile-height band rather than full-frame float32
RGB and weight buffers. The final array is a disk-backed memmap.
"""
from pathlib import Path
import numpy as np
from .tiler import MultiDiffusionTiler, generate_gaussian_weights, generate_cosine_weights


def process_streamed(tiler: MultiDiffusionTiler, image: np.ndarray, tile_fn, output_path, progress_callback=None):
    """Stream rows into output_path. Caller owns the resulting memmap file.

    Blend workspace: O(output_width * output_tile_height * channels).
    Temporary disk usage: O(output_pixels), without a float32 full-frame blend.
    """
    if not isinstance(image, np.ndarray) or image.ndim not in (2, 3) or min(image.shape[:2]) < 1:
        raise ValueError("image must be a nonempty 2D or 3D numpy array")
    if image.ndim == 3 and image.shape[2] < 1:
        raise ValueError("image must have at least one channel")
    h, w = image.shape[:2]
    channels = image.shape[2] if image.ndim == 3 else 1
    scale = tiler.scale
    tile_size = tiler.tile_size // scale
    overlap = min(tiler.overlap // scale, tile_size - 1)
    tiles = tiler.compute_tile_grid_custom(h, w, tile_size, overlap)
    dest = Path(output_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dtype = np.uint8 if image.dtype == np.uint8 else np.float32
    output = np.memmap(dest, dtype=dtype, mode="w+", shape=(h * scale, w * scale, channels))
    band_start = 0
    capacity = min(h, tile_size) * scale
    canvas = np.zeros((capacity, w * scale, channels), dtype=np.float32)
    weights = np.zeros((capacity, w * scale, 1), dtype=np.float32)
    try:
        for index, (y1, y2, x1, x2) in enumerate(tiles):
            next_start = y1 * scale
            if next_start > band_start:
                flush = next_start - band_start
                if np.any(weights[:flush] <= 0):
                    raise RuntimeError("Tiling left uncovered output pixels")
                result = canvas[:flush] / weights[:flush]
                if dtype == np.uint8:
                    result = np.clip(result + 0.5, 0, 255).astype(np.uint8)
                output[band_start:next_start] = result
                left = capacity - flush
                if left:
                    canvas[:left] = canvas[flush:].copy()
                    weights[:left] = weights[flush:].copy()
                canvas[left:] = 0
                weights[left:] = 0
                band_start = next_start
            tile_out = np.asarray(tile_fn(image[y1:y2, x1:x2]))
            if tile_out.ndim == 2:
                tile_out = tile_out[..., None]
            expected = ((y2 - y1) * scale, (x2 - x1) * scale, channels)
            if tile_out.shape != expected:
                raise ValueError(f"Tile {index + 1} returned shape {tile_out.shape}, expected {expected}")
            if not (np.issubdtype(tile_out.dtype, np.integer) or np.issubdtype(tile_out.dtype, np.floating)) or not np.all(np.isfinite(tile_out)):
                raise ValueError(f"Tile {index + 1} returned non-finite or non-numeric pixels")
            th, tw = tile_out.shape[:2]
            if tiler.weight_type == "gaussian":
                tile_weights = generate_gaussian_weights(th, tw)
            else:
                tile_weights = generate_cosine_weights(
                    th, tw, overlap * scale, overlap * scale,
                    fade_top=y1 > 0, fade_bottom=y2 < h,
                    fade_left=x1 > 0, fade_right=x2 < w,
                )
            by1, bx1 = y1 * scale - band_start, x1 * scale
            by2, bx2 = by1 + th, bx1 + tw
            canvas[by1:by2, bx1:bx2] += tile_out.astype(np.float32) * tile_weights[..., None]
            weights[by1:by2, bx1:bx2] += tile_weights[..., None]
            if progress_callback:
                progress_callback((index + 1) / len(tiles))
        tail_len = h * scale - band_start
        if np.any(weights[:tail_len] <= 0):
            raise RuntimeError("Tiling left uncovered output pixels")
        tail = canvas[:tail_len] / weights[:tail_len]
        if dtype == np.uint8:
            tail = np.clip(tail + 0.5, 0, 255).astype(np.uint8)
        output[band_start:] = tail
        output.flush()
    except BaseException:
        del output
        dest.unlink(missing_ok=True)
        raise
    if image.ndim == 2:
        return output.reshape(h * scale, w * scale)
    return output
