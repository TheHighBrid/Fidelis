"""Unsigned image execution provenance; does not claim C2PA signature verification."""
from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def compute_sha256(file_path: Path | str) -> str:
    """Compute SHA-256 digest of a file."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def generate_c2pa_provenance(
    input_path: Path | str,
    output_path: Path | str,
    model_profile: str,
    scale: int,
    tile_size: int,
    output_sha256: str,
) -> dict[str, Any]:
    """Write an unsigned provenance record, not a signed or verified C2PA manifest."""
    input_sha256 = compute_sha256(input_path)
    claim = {
        "claim_generator": "Fidelis-Precision-Engine/2.0",
        "format": "application/vnd.fidelis.provenance+json",
        "title": "Fidelis Super-Resolution & Photographic Enhancement",
        "assertions": [
            {
                "label": "c2pa.actions",
                "data": {
                    "actions": [
                        {
                            "action": "c2pa.upscaled",
                            "parameters": {
                                "scale": scale,
                                "model_profile": model_profile,
                                "tile_size": tile_size,
                            },
                            "softwareAgent": "Fidelis Precision Engine v2.0",
                        }
                    ]
                },
            },
            {
                "label": "c2pa.hash.data",
                "data": {
                    "input_sha256": input_sha256,
                    "output_sha256": output_sha256,
                    "algorithm": "sha256",
                },
            },
        ],
        "signature_info": {
            "status": "unsigned",
            "issuer": None,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        },
    }

    # Legacy .c2pa.json filename retained for consumers; content is NOT signed C2PA.
    sidecar_path = Path(output_path).with_suffix(Path(output_path).suffix + ".c2pa.json")
    try:
        with open(sidecar_path, "w", encoding="utf-8") as f:
            json.dump(claim, f, indent=2)
    except OSError as e:
        claim["signature_info"]["status"] = "write_failed"
        logger.warning("Could not write unsigned provenance sidecar: %s", e)

    return claim
