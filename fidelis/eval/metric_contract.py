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
    if not isinstance(metrics, Mapping):
        return "Quality:      unavailable (invalid metric payload)"
    if any(isinstance(key, str) and key.casefold() == "lpips" for key in metrics):
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


def sanitize_quality_payload(metrics: Mapping[str, Any], *, reference_kind: str | None = None) -> dict[str, Any]:
    """Produce a fail-closed machine-readable metric record for telemetry.

    Legacy numeric values are never forwarded without an explicitly declared
    reference type. This does not authenticate a reference: the caller must
    establish independent provenance before setting reference_kind.
    """
    if reference_kind is None:
        return {"status": "unavailable", "reason": "reference_not_verified", "metrics": {}}
    if reference_kind not in {"ground_truth", "source_consistency"}:
        raise ValueError("Unknown quality reference kind")
    if not isinstance(metrics, Mapping):
        return {"status": "unavailable", "reason": "invalid_payload", "metrics": {}}
    if any(isinstance(key, str) and key.casefold() == "lpips" for key in metrics):
        return {"status": "unavailable", "reason": "unverified_lpips", "metrics": {}}
    values: dict[str, float] = {}
    for key in ("psnr", "ssim"):
        value = metrics.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            return {"status": "unavailable", "reason": "invalid_metrics", "metrics": {}}
        values[key] = float(value)
    if values["psnr"] < 0 or not 0 <= values["ssim"] <= 1:
        return {"status": "unavailable", "reason": "out_of_range", "metrics": {}}
    return {"status": "measured", "reference_kind": reference_kind,
            "is_ground_truth": reference_kind == "ground_truth", "metrics": values}


def sanitize_legacy_manifest(manifest: Mapping[str, Any]) -> dict[str, Any]:
    """Remove unsupported legacy quality claims from exported CLI manifests.

    The legacy pipeline also embeds quality values in root span attributes.
    Preserve non-quality execution evidence while removing those claims.
    This is an export boundary, not a correction to upstream telemetry.
    """
    if not isinstance(manifest, Mapping):
        raise ValueError("Invalid execution manifest")
    from copy import deepcopy

    result = deepcopy(dict(manifest))
    result["metrics"] = sanitize_quality_payload(result.get("metrics"))
    quality_keys = {
        "psnr", "psnr_db", "ssim", "ssim_score", "lpips", "lpips_proxy",
        "cielab_delta_e", "gradient_coherence_pct",
    }

    def redact_quality_attributes(value: Any) -> None:
        """Redact quality claims inside span attributes, including nested records.

        Only traverse the attributes subtree, not arbitrary execution metadata:
        hashes, timings and non-quality evidence must survive export.
        """
        if isinstance(value, dict):
            for key in list(value):
                if isinstance(key, str) and key.casefold() in quality_keys:
                    value.pop(key, None)
            for child in value.values():
                redact_quality_attributes(child)
        elif isinstance(value, list):
            for child in value:
                redact_quality_attributes(child)

    # Other exporters may attach span-like events and telemetry outside "spans".
    # Redact their nested claims as well, while retaining the root-level
    # normalized metrics contract and unrelated execution evidence.
    for key in list(result):
        if isinstance(key, str) and key.casefold() in quality_keys:
            result.pop(key, None)
    for key, value in result.items():
        if key != "metrics":
            redact_quality_attributes(value)
    return result
