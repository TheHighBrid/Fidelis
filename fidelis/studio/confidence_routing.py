"""Conservative semantic probability routing, not an automatic segmentation model.

Unknown and ambiguous pixels stay on the precision base. Explicit protection
wins. All supplied probability maps must already be on the precision-base grid.
"""
from __future__ import annotations

from collections.abc import Mapping
import numpy as np

CLASSES = ("skin", "hair", "fabric")


def route_confidence_masks(
    probabilities: Mapping[str, np.ndarray],
    *,
    protect: np.ndarray,
    threshold: float = 0.80,
    margin: float = 0.15,
    confidence: np.ndarray | None = None,
) -> dict[str, np.ndarray]:
    """Return mutually exclusive float32 class masks plus an explicit protect map.

    Class probabilities need not sum to one: background/unknown may own the
    remaining probability. A winner must pass threshold and strictly beat the
    runner-up, including when margin=0. Confidence only attenuates contribution.
    Fully protected pixels have zero generated contribution.
    """
    if set(probabilities) != set(CLASSES):
        raise ValueError("probabilities must contain exactly skin, hair, fabric")
    if not np.isfinite(threshold) or not 0 < threshold <= 1:
        raise ValueError("threshold must be finite and in (0, 1]")
    if not np.isfinite(margin) or not 0 <= margin <= 1:
        raise ValueError("margin must be finite and in [0, 1]")

    def valid(name: str, value: np.ndarray, shape: tuple[int, int] | None = None) -> np.ndarray:
        a = np.asarray(value)
        if a.ndim != 2 or a.size == 0 or (shape is not None and a.shape != shape):
            raise ValueError(f"{name} must be a nonempty aligned 2D map")
        if not np.issubdtype(a.dtype, np.number) or np.iscomplexobj(a):
            raise ValueError(f"{name} must be real numeric data")
        if not np.all(np.isfinite(a)) or np.any(a < 0) or np.any(a > 1):
            raise ValueError(f"{name} must contain finite values in [0, 1]")
        return a.astype(np.float32, copy=True)

    lock = valid("protect", protect)
    shape = lock.shape
    stack = np.stack([valid(label, probabilities[label], shape) for label in CLASSES], axis=0)
    certainty = np.ones(shape, dtype=np.float32) if confidence is None else valid("confidence", confidence, shape)
    winner = np.argmax(stack, axis=0)
    top = np.max(stack, axis=0)
    runner_up = np.partition(stack, -2, axis=0)[-2]
    gap = top - runner_up
    allowed = (top >= threshold) & (gap > 0) & (gap >= margin) & (lock < 1)
    weight = np.where(allowed, top * certainty * (1 - lock), 0).astype(np.float32)
    result = {label: np.where(winner == i, weight, 0).astype(np.float32) for i, label in enumerate(CLASSES)}
    result["protect"] = lock
    return result
