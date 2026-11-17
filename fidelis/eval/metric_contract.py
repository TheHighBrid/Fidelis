"""Fail-closed presentation of image quality metrics.

Legacy pipeline metrics can contain placeholders and a gradient-derived value
named LPIPS. They are never accepted as ground-truth quality evidence without
an explicit reference contract.
"""
from __future__ import annotations

import math
from typing import Mapping, Any


def format_quality_summary(metrics: Mapping[str, Any], *, reference_kind: str | None = None) -> str:
    """Return a human-readable report without inventing benchmark evidence.

    reference_kind='ground_truth' is reserved for an independently verified,
    aligned ground-truth reference. 'source_consistency' describes downsampled
    output compared with the input and is NOT restoration accuracy.
    """
    if reference_kind is None:
        return "Quality:      unavailable (legacy metrics lack verified reference/provenance)"
    if reference_kind not in {"ground_truth", "source_consistency"}:
        raise ValueError("Unknown quality reference kind")
    if "lpips" in metrics:
        raise ValueError("Legacy gradient-derived 'lpips' is not a real LPIPS measurement")
    values = []
    for key in ("psnr", "ssim"):
        value = metrics.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            return "Quality:      unavailable (missing or invalid PSNR/SSIM)"
        values.append(float(value))
    psnr, ssim = values
    if psnr < 0 or not 0 <= ssim <= 1:
        return "Quality:      unavailable (out-of-range PSNR/SSIM)"
    label = "ground-truth reference" if reference_kind == "ground_truth" else "source consistency only; not recovery accuracy"
    return f"PSNR / SSIM:  {psnr:.2f} dB / {ssim:.4f} ({label}; no LPIPS measured)"
