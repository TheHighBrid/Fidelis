"""PNG and protect-mask helpers for the RealeSR-general-v3 qualifier."""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

SCALE = 4


class QualificationError(Exception):
    def __init__(self, message: str, code: int = 1):
        super().__init__(message)
        self.code = code


def load_rgb_png(path: Path) -> np.ndarray:
    try:
        with Image.open(path) as image:
            if image.format != 'PNG':
                raise QualificationError(f'{path} must be a PNG file')
            if image.mode != 'RGB':
                raise QualificationError(f'{path} must be untagged 8-bit RGB')
            if image.info.get('icc_profile'):
                raise QualificationError(f'{path} carries an ICC profile outside this workflow contract')
            orientation = image.getexif().get(274)
            if orientation not in (None, 1):
                raise QualificationError(f'{path} has an EXIF orientation outside this workflow contract')
            pixels = np.array(image, copy=True)
    except QualificationError:
        raise
    except (OSError, ValueError) as exc:
        raise QualificationError(f'{path} could not be read: {exc}') from exc
    return _require_rgb_array(path, pixels)


def _require_rgb_array(path: Path, pixels: np.ndarray) -> np.ndarray:
    if pixels.dtype != np.uint8 or pixels.ndim != 3 or pixels.shape[2] != 3:
        raise QualificationError(f'{path} must be 8-bit RGB')
    if pixels.shape[0] == 0 or pixels.shape[1] == 0:
        raise QualificationError(f'{path} has no pixels')
    return pixels


def save_rgb_png(path: Path, pixels: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(pixels, mode='RGB').save(path, format='PNG')


def expected_size(width: int, height: int) -> tuple[int, int]:
    return width * SCALE, height * SCALE


def require_expected_scale(
    actual_width: int,
    actual_height: int,
    expected_width: int,
    expected_height: int,
    subject: str = 'output',
) -> None:
    if actual_width != expected_width or actual_height != expected_height:
        raise QualificationError(
            f'{subject} dimensions {actual_width}x{actual_height} do not match expected '
            f'scale {SCALE} ({expected_width}x{expected_height}); refusing to resize'
        )


def validate_protect_mask(mask: np.ndarray) -> None:
    if mask.ndim != 2 or not np.issubdtype(mask.dtype, np.number):
        raise QualificationError('protect mask must be a numeric HxW array')
    if not np.all(np.isfinite(mask)) or np.any((mask < 0) | (mask > 1)):
        raise QualificationError('protect mask values must be finite within [0, 1]')


def load_protect_mask(path: Path) -> np.ndarray:
    try:
        with np.load(path, allow_pickle=False) as data:
            if 'protect' not in data.files:
                raise QualificationError('NPZ requires a protect mask')
            mask = np.array(data['protect'])
    except QualificationError:
        raise
    except (OSError, ValueError, KeyError) as exc:
        raise QualificationError(f'protect mask could not be read: {exc}') from exc
    validate_protect_mask(mask)
    return mask


def align_protect_mask(mask: np.ndarray, input_shape: tuple[int, int], output_shape: tuple[int, int]) -> np.ndarray:
    """Accept an input-sized or output-sized mask.

    An input-sized mask is repeated as exact scale-by-scale blocks. Any other
    shape stops the run. The mask is not interpolated onto the output.
    """
    if mask.shape == output_shape:
        return mask
    if mask.shape == input_shape:
        return np.repeat(np.repeat(mask, SCALE, axis=0), SCALE, axis=1)
    in_h, in_w = input_shape
    out_h, out_w = output_shape
    raise QualificationError(
        f'protect mask shape {mask.shape[1]}x{mask.shape[0]} matches neither the input '
        f'{in_w}x{in_h} nor the expected output {out_w}x{out_h}; refusing to resize'
    )


def integer_replicate_rgb(image: np.ndarray) -> np.ndarray:
    if image.ndim != 3 or image.shape[2] != 3 or image.dtype != np.uint8:
        raise QualificationError('precision source must be uint8 RGB')
    return np.repeat(np.repeat(image, SCALE, axis=0), SCALE, axis=1)


def composite_protected(base: np.ndarray, texture: np.ndarray, mask: np.ndarray) -> np.ndarray:
    if base.shape != texture.shape or base.dtype != np.uint8 or texture.dtype != np.uint8:
        raise QualificationError('texture and base must be uint8 RGB arrays of equal shape')
    if mask.shape != base.shape[:2]:
        raise QualificationError('protect mask dimensions differ from base')
    validate_protect_mask(mask)
    export = np.array(texture, copy=True)
    export[mask == 1] = base[mask == 1]
    return export


def prepare_base(source: np.ndarray, base_path: Path | None, expected: tuple[int, int]) -> np.ndarray:
    if base_path is None:
        return integer_replicate_rgb(source)
    base = load_rgb_png(base_path)
    require_expected_scale(base.shape[1], base.shape[0], expected[0], expected[1], subject='base')
    return base
