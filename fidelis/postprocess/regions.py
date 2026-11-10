"""Conservative, linear-light composition of already aligned RGB passes.

No inference or segmentation is implied. Callers supply explicit semantic masks.
Fully protected pixels are restored *after* conversion, preserving exact base bytes.
"""
from dataclasses import dataclass
import math

import numpy as np


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


def _rgb(value, name):
    arr = np.asarray(value)
    if arr.ndim != 3 or arr.shape[2] != 3 or min(arr.shape[:2]) < 1:
        raise ValueError(f"{name} must have nonempty H x W x 3 shape")
    if arr.dtype != np.uint8:
        raise ValueError(f"{name} must be uint8 sRGB; explicit conversion is required")
    return arr


def compose_regions(base, texture, *, skin=None, hair=None, fabric=None,
                    protected=None, confidence=None, edge_guard=None,
                    blend=RegionBlend()):
    """Return (uint8 sRGB result, float32 effective alpha).

    Masks are H x W floats in [0,1] on the exact base grid. Overlapping semantic
    probabilities normalize to at most one; unclassified mass stays base.
    Confidence is required for any generated contribution (missing means zero).
    Protected=1 is an exact lock; fractional values attenuate alpha. The optional
    edge guard is a caller-supplied heuristic, not hardware/seam segmentation.
    This function verifies shape, not internal spatial registration.
    """
    base = _rgb(base, "base")
    texture = _rgb(texture, "texture")
    if base.shape != texture.shape:
        raise ValueError("passes must have identical dimensions; no implicit resizing")
    shape = base.shape[:2]
    skin = _mask(skin, shape, "skin")
    hair = _mask(hair, shape, "hair")
    fabric = _mask(fabric, shape, "fabric")
    protected = _mask(protected, shape, "protected")
    confidence = _mask(confidence, shape, "confidence")
    edge_guard = _mask(edge_guard, shape, "edge_guard")
    total = np.maximum(1.0, skin + hair + fabric)
    alpha = (skin * blend.skin + hair * blend.hair + fabric * blend.fabric) / total
    alpha *= confidence * (1.0 - protected)
    alpha *= 1.0 - edge_guard * blend.edge_protection
    alpha = np.clip(alpha, 0.0, 1.0)

    # A lookup table avoids full-frame transfer-function intermediates for inputs.
    srgb = np.arange(256, dtype=np.float32) / 255.0
    lut = np.where(srgb <= .04045, srgb / 12.92, ((srgb + .055) / 1.055) ** 2.4)
    linear = lut[base] * (1.0 - alpha[..., None]) + lut[texture] * alpha[..., None]
    result = np.where(linear <= .0031308, linear * 12.92,
                      1.055 * np.maximum(linear, 0) ** (1 / 2.4) - .055)
    result = np.clip(np.rint(result * 255), 0, 255).astype(np.uint8)
    # Hard protection also excludes any quantization or future finishing changes.
    locked = (protected == 1.0) | (alpha == 0.0)
    result[locked] = base[locked]
    return result, alpha
