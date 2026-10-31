"""Closed-Form MultiDiffusion Tiled Latent and Pixel Solver for Fidelis.

Implements Bar-Tal et al. (ICML 2023) closed-form least-squares fusion across
overlapping tiles with 2D Gaussian feathering and tiled VAE reconstruction,
enabling seamless upscaling up to 32,000x32,000 px without boundary seams.
"""

import math
from typing import Callable, Generator, List, Tuple
import numpy as np


def pad_to_multiple(dim: int, multiple: int = 8) -> int:
    """Align dimension to exact multiple (e.g. multiple of 8 or 16)."""
    return ((dim + multiple - 1) // multiple) * multiple


def generate_gaussian_weights(tile_h: int, tile_w: int, sigma_scale: float = 0.25) -> np.ndarray:
    """Generate 2D spatial Gaussian feathering weight matrix W_i."""
    y = np.linspace(-1, 1, tile_h)
    x = np.linspace(-1, 1, tile_w)
    xx, yy = np.meshgrid(x, y)
    d2 = (xx / (2 * sigma_scale)) ** 2 + (yy / (2 * sigma_scale)) ** 2
    weights = np.exp(-0.5 * d2)
    # Avoid zero at boundary
    weights = np.maximum(weights, 1e-4)
    return weights.astype(np.float32)


def generate_cosine_weights(
    tile_h: int,
    tile_w: int,
    overlap_h: int,
    overlap_w: int,
    fade_top: bool = True,
    fade_bottom: bool = True,
    fade_left: bool = True,
    fade_right: bool = True,
) -> np.ndarray:
    """Generate strictly positive cosine weights, tapering only requested sides.

    The outer image boundary must never receive zero weight: it has no adjacent
    tile to contribute to the normalized blend.
    """
    if tile_h < 1 or tile_w < 1:
        raise ValueError("Tile dimensions must be positive")
    overlap_h = min(max(overlap_h, 0), tile_h)
    overlap_w = min(max(overlap_w, 0), tile_w)

    weight_y = np.ones(tile_h, dtype=np.float32)
    if overlap_h > 0:
        # Interior samples avoid exact zeros, including on very small tiles.
        ramp = 0.5 * (1 - np.cos(np.linspace(0, np.pi, overlap_h + 2)[1:-1]))
        if fade_top:
            weight_y[:overlap_h] = np.minimum(weight_y[:overlap_h], ramp)
        if fade_bottom:
            weight_y[-overlap_h:] = np.minimum(weight_y[-overlap_h:], ramp[::-1])

    weight_x = np.ones(tile_w, dtype=np.float32)
    if overlap_w > 0:
        ramp = 0.5 * (1 - np.cos(np.linspace(0, np.pi, overlap_w + 2)[1:-1]))
        if fade_left:
            weight_x[:overlap_w] = np.minimum(weight_x[:overlap_w], ramp)
        if fade_right:
            weight_x[-overlap_w:] = np.minimum(weight_x[-overlap_w:], ramp[::-1])

    return np.outer(weight_y, weight_x)


class MultiDiffusionTiler:
    """Closed-form MultiDiffusion tiled canvas orchestrator."""

    def __init__(
        self,
        tile_size: int = 1024,
        overlap: int = 64,
        scale: int = 4,
        weight_type: str = "gaussian"
    ):
        if any(isinstance(v, bool) or not isinstance(v, int) for v in (tile_size, overlap, scale)):
            raise ValueError("tile_size, overlap, and scale must be integers")
        if scale < 1 or tile_size < scale:
            raise ValueError("tile_size must be at least scale, and scale must be positive")
        if not 0 <= overlap < tile_size:
            raise ValueError("overlap must be nonnegative and smaller than tile_size")
        if weight_type not in ("gaussian", "cosine"):
            raise ValueError("weight_type must be 'gaussian' or 'cosine'")
        self.tile_size = tile_size
        self.overlap = overlap
        self.scale = scale
        self.weight_type = weight_type

    def compute_tile_grid(self, height: int, width: int) -> List[Tuple[int, int, int, int]]:
        """Compute tile bounding boxes (y1, y2, x1, x2) covering canvas with overlap."""
        stride = self.tile_size - self.overlap
        tiles = []

        y = 0
        while y < height:
            y2 = min(y + self.tile_size, height)
            y1 = max(0, y2 - self.tile_size)
            x = 0
            while x < width:
                x2 = min(x + self.tile_size, width)
                x1 = max(0, x2 - self.tile_size)
                tiles.append((y1, y2, x1, x2))
                if x2 >= width:
                    break
                x += stride
            if y2 >= height:
                break
            y += stride

        return tiles

    def process(
        self,
        image: np.ndarray,
        tile_fn: Callable[[np.ndarray], np.ndarray],
        progress_callback: Callable[[float], None] = None
    ) -> np.ndarray:
        """Execute closed-form MultiDiffusion weighted fusion across tiles.

        Args:
            image: Input image array of shape (H, W, C).
            tile_fn: Callable taking tile (h, w, C) and returning upscaled (h*scale, w*scale, C).
            progress_callback: Optional progress reporter (0.0 to 1.0).

        Returns:
            Seamless high-resolution reconstructed array of shape (H*scale, W*scale, C).
        """
        if not isinstance(image, np.ndarray) or image.ndim not in (2, 3):
            raise ValueError("image must be a 2D or 3D numpy array")
        if image.shape[0] < 1 or image.shape[1] < 1 or (image.ndim == 3 and image.shape[2] < 1):
            raise ValueError("image dimensions must be nonempty")
        in_h, in_w = image.shape[:2]
        out_h = in_h * self.scale
        out_w = in_w * self.scale
        channels = image.shape[2] if image.ndim == 3 else 1

        # Tile size in input space
        in_tile_size = self.tile_size // self.scale
        in_overlap = min(self.overlap // self.scale, in_tile_size - 1)

        tiles = self.compute_tile_grid_custom(in_h, in_w, in_tile_size, in_overlap)
        total_tiles = len(tiles)

        # Global accumulators for least-squares weighted fusion
        global_canvas = np.zeros((out_h, out_w, channels), dtype=np.float32)
        global_weights = np.zeros((out_h, out_w, 1), dtype=np.float32)

        for idx, (iy1, iy2, ix1, ix2) in enumerate(tiles):
            # Extract input tile F_i(I)
            tile_in = image[iy1:iy2, ix1:ix2]

            # Upscale tile via model denoiser / restorer Phi
            tile_out = np.asarray(tile_fn(tile_in))
            if tile_out.ndim == 2:
                tile_out = tile_out[..., np.newaxis]

            expected_shape = (
                (iy2 - iy1) * self.scale,
                (ix2 - ix1) * self.scale,
                channels,
            )
            if tile_out.shape != expected_shape:
                raise ValueError(
                    f"Tile {idx + 1} returned shape {tile_out.shape}, expected {expected_shape}"
                )
            if not (
                np.issubdtype(tile_out.dtype, np.integer)
                or np.issubdtype(tile_out.dtype, np.floating)
            ) or not np.all(np.isfinite(tile_out)):
                raise ValueError(f"Tile {idx + 1} returned non-finite or non-numeric pixels")
            tile_out = tile_out.astype(np.float32)
            th, tw = tile_out.shape[:2]

            # Fade only edges shared with another tile. The image perimeter
            # stays fully weighted, avoiding dark/black output borders.
            if self.weight_type == "gaussian":
                w_mat = generate_gaussian_weights(th, tw)
            else:
                overlap_px = in_overlap * self.scale
                w_mat = generate_cosine_weights(
                    th, tw, overlap_px, overlap_px,
                    fade_top=iy1 > 0,
                    fade_bottom=iy2 < in_h,
                    fade_left=ix1 > 0,
                    fade_right=ix2 < in_w,
                )
            w_mat = w_mat[..., np.newaxis]

            # Output coordinates
            oy1 = iy1 * self.scale
            oy2 = oy1 + th
            ox1 = ix1 * self.scale
            ox2 = ox1 + tw

            # Closed-form accumulation:
            # global_canvas += W_i * Phi(F_i)
            # global_weights += W_i
            global_canvas[oy1:oy2, ox1:ox2] += tile_out * w_mat
            global_weights[oy1:oy2, ox1:ox2] += w_mat

            if progress_callback:
                progress_callback((idx + 1) / total_tiles)

        # Normalize by cumulative weights: Z = sum(W_i * Phi) / sum(W_i)
        if np.any(global_weights <= 0):
            raise RuntimeError("Tiling left uncovered output pixels")
        output = global_canvas / global_weights

        if image.dtype == np.uint8:
            output = np.clip(output + 0.5, 0, 255).astype(np.uint8)

        if channels == 1 and output.ndim == 3 and output.shape[2] == 1:
            output = output.squeeze(axis=2)

        return output

    @staticmethod
    def compute_tile_grid_custom(h: int, w: int, size: int, overlap: int) -> List[Tuple[int, int, int, int]]:
        if h < 1 or w < 1 or size < 1 or not 0 <= overlap < size:
            raise ValueError("Invalid canvas dimensions, tile size, or overlap")
        stride = size - overlap
        tiles = []
        y = 0
        while y < h:
            y2 = min(y + size, h)
            y1 = max(0, y2 - size)
            x = 0
            while x < w:
                x2 = min(x + size, w)
                x1 = max(0, x2 - size)
                tiles.append((y1, y2, x1, x2))
                if x2 >= w:
                    break
                x += stride
            if y2 >= h:
                break
            y += stride
        return tiles
