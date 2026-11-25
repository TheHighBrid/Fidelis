"""Conservative, linear-light composition of already aligned RGB passes.

No inference or segmentation is implied. Callers supply explicit semantic masks.
Fully protected pixels are restored *after* conversion, preserving exact base bytes.
"""
import math
from dataclasses import dataclass

import numpy as np

_COMPOSE_STRIP_ROWS = 256


@dataclass(frozen=True)
class RegionBlend:
    skin: float = 0.25
    hair: float = 0.20
    fabric: float = 0.15
    edge_protection: float = 0.0

    def __post_init__(self):
        for name in ("skin", "hair", "fabric", "edge_protection"):
            value = getattr(self, name)
            if not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError(f"{name} must be finite and in [0, 1]")


PROFILES = {
    "luxury_apparel": RegionBlend(),
    "editorial_skin": RegionBlend(skin=0.30, hair=0.20, fabric=0.0),
    "macro_product": RegionBlend(skin=0.0, hair=0.0, fabric=0.10),
    "packshot_strict": RegionBlend(skin=0.0, hair=0.0, fabric=0.0),
}


def _mask(value, shape, name):
    if value is None:
        return np.zeros(shape, dtype=np.float32)
    arr = np.asarray(value)
    if arr.shape != shape or arr.dtype.kind not in "uif":
        raise ValueError(f"{name} must be a numeric mask of shape {shape}")
    if not np.all(np.isfinite(arr)) or np.any(arr < 0) or np.any(arr > 1):
        raise ValueError(f"{name} must contain finite values in [0, 1]")
    return arr.astype(np.float32, copy=False)


def _validate_optional_mask(value, shape, name):
    if value is None:
        return None
    arr = np.asarray(value)
    if arr.shape != shape or arr.dtype.kind not in "uif":
        raise ValueError(f"{name} must be a numeric mask of shape {shape}")
    height = shape[0]
    for y0 in range(0, height, _COMPOSE_STRIP_ROWS):
        strip = arr[y0:min(height, y0 + _COMPOSE_STRIP_ROWS)]
        if not np.all(np.isfinite(strip)) or np.any(strip < 0) or np.any(strip > 1):
            raise ValueError(f"{name} must contain finite values in [0, 1]")
    return arr


def _mask_strip(arr, y0, y1, width):
    if arr is None:
        return np.zeros((y1 - y0, width), dtype=np.float32)
    return arr[y0:y1].astype(np.float32, copy=False)


def _rgb(value, name):
    arr = np.asarray(value)
    if arr.ndim != 3 or arr.shape[2] != 3 or min(arr.shape[:2]) < 1:
        raise ValueError(f"{name} must have nonempty H x W x 3 shape")
    if arr.dtype != np.uint8:
        raise ValueError(f"{name} must be uint8 sRGB; explicit conversion is required")
    return arr


def _srgb_linear_lut(dtype):
    sample_max = np.iinfo(dtype).max
    srgb = np.arange(sample_max + 1, dtype=np.float32) / sample_max
    return np.where(srgb <= .04045, srgb / 12.92, ((srgb + .055) / 1.055) ** 2.4)


@dataclass(frozen=True)
class _ComposeSpec:
    blend: RegionBlend
    base_lut: np.ndarray
    tex_lut: np.ndarray
    target_dtype: np.dtype
    output_max: int
    scale_factor: int


def _validate_compose_inputs(base, texture, output_dtype):
    for image, name in ((base, "base"), (texture, "texture")):
        if image.dtype != np.uint16:
            _rgb(image, name)
        elif image.ndim != 3 or image.shape[2] != 3 or min(image.shape[:2]) < 1:
            raise ValueError(f"{name} must have nonempty H x W x 3 shape")
    target_dtype = np.dtype(output_dtype if output_dtype is not None else base.dtype)
    if target_dtype not in (np.dtype(np.uint8), np.dtype(np.uint16)) or target_dtype.itemsize < base.dtype.itemsize:
        raise ValueError("Output must retain at least the base sample precision")
    if base.shape != texture.shape:
        raise ValueError("passes must have identical dimensions; no implicit resizing")
    return target_dtype


def _strip_alpha(masks, y0, y1, width, blend):
    skin = _mask_strip(masks["skin"], y0, y1, width)
    hair = _mask_strip(masks["hair"], y0, y1, width)
    fabric = _mask_strip(masks["fabric"], y0, y1, width)
    prot = _mask_strip(masks["protected"], y0, y1, width)
    conf = _mask_strip(masks["confidence"], y0, y1, width)
    edge = _mask_strip(masks["edge_guard"], y0, y1, width)
    if masks["interior_texture"] is not None:
        edge = edge * (1.0 - _mask_strip(masks["interior_texture"], y0, y1, width))
    total = np.maximum(1.0, skin + hair + fabric)
    alpha = (skin * blend.skin + hair * blend.hair + fabric * blend.fabric) / total
    alpha *= conf * (1.0 - prot)
    alpha *= 1.0 - edge * blend.edge_protection
    return np.clip(alpha, 0.0, 1.0), prot


def _compose_strip(base_strip, tex_strip, alpha_strip, prot_strip, spec):
    linear = spec.base_lut[base_strip] * (1.0 - alpha_strip[..., None]) + spec.tex_lut[tex_strip] * alpha_strip[..., None]
    srgb = np.where(linear <= .0031308, linear * 12.92,
                    1.055 * np.maximum(linear, 0) ** (1 / 2.4) - .055)
    res_strip = np.clip(np.rint(srgb * spec.output_max), 0, spec.output_max).astype(spec.target_dtype)
    locked = (prot_strip == 1.0) | (alpha_strip == 0.0)
    if np.any(locked):
        res_strip[locked] = base_strip[locked].astype(spec.target_dtype) * spec.scale_factor
    return res_strip


def compose_regions(base, texture, *, skin=None, hair=None, fabric=None,
                    protected=None, confidence=None, edge_guard=None,
                    interior_texture=None,
                    blend=None, output_dtype=None):
    """Return (sRGB result at requested precision, float32 effective alpha).

    Masks are H x W floats in [0,1] on the exact base grid. Overlapping semantic
    probabilities normalize to at most one; unclassified mass stays base.
    Confidence is required for any generated contribution (missing means zero).
    Protected=1 is an exact lock; fractional values attenuate alpha. The optional
    edge guard is a caller-supplied heuristic, not hardware/seam segmentation.
    This function verifies shape, not internal spatial registration.
    """
    if blend is None:
        blend = RegionBlend()
    base = np.asarray(base)
    texture = np.asarray(texture)
    target_dtype = _validate_compose_inputs(base, texture, output_dtype)
    source_max = np.iinfo(base.dtype).max
    output_max = np.iinfo(target_dtype).max
    spec = _ComposeSpec(
        blend=blend,
        base_lut=_srgb_linear_lut(base.dtype),
        tex_lut=_srgb_linear_lut(texture.dtype),
        target_dtype=target_dtype,
        output_max=output_max,
        scale_factor=output_max // source_max,
    )
    height, width = base.shape[:2]
    shape = (height, width)
    masks = {
        "skin": _validate_optional_mask(skin, shape, "skin"),
        "hair": _validate_optional_mask(hair, shape, "hair"),
        "fabric": _validate_optional_mask(fabric, shape, "fabric"),
        "protected": _validate_optional_mask(protected, shape, "protected"),
        "confidence": _validate_optional_mask(confidence, shape, "confidence"),
        "edge_guard": _validate_optional_mask(edge_guard, shape, "edge_guard"),
        "interior_texture": _validate_optional_mask(interior_texture, shape, "interior_texture"),
    }
    result = np.empty(base.shape, dtype=target_dtype)
    alpha_out = np.empty(shape, dtype=np.float32)
    for y0 in range(0, height, _COMPOSE_STRIP_ROWS):
        y1 = min(height, y0 + _COMPOSE_STRIP_ROWS)
        s_alpha, s_prot = _strip_alpha(masks, y0, y1, width, blend)
        alpha_out[y0:y1] = s_alpha
        result[y0:y1] = _compose_strip(base[y0:y1], texture[y0:y1], s_alpha, s_prot, spec)
    return result, alpha_out
