#!/usr/bin/env python3
"""Reblend aligned sRGB PNG passes with explicit masks, without new inference."""
import argparse
from dataclasses import asdict, replace
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fidelis.postprocess.regions import PROFILES, compose_regions


def digest(path):
    h = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_pass(path):
    with Image.open(path) as image:
        # First CLI deliberately rejects implicit colour/orientation/alpha changes.
        if image.format != "PNG" or image.mode != "RGB":
            raise ValueError("passes must be 8-bit RGB PNGs in sRGB working space")
        if image.getexif().get(274, 1) != 1:
            raise ValueError("normalize EXIF orientation before composition")
        return np.array(image), image.info.get("icc_profile")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base", type=Path)
    parser.add_argument("texture", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--masks", type=Path, required=True,
                        help="NPZ with skin/hair/fabric/protected/confidence/edge_guard float masks")
    parser.add_argument("--profile", choices=PROFILES, default="luxury_apparel")
    for name in ("skin", "hair", "fabric", "edge-protection"):
        parser.add_argument("--" + name, type=float)
    args = parser.parse_args()
    try:
        if args.output.suffix.lower() != ".png":
            raise ValueError("output must be a PNG file")
        sidecar = args.output.with_suffix(".png.recipe.json")
        inputs = {p.resolve() for p in (args.base, args.texture, args.masks)}
        if args.output.resolve() in inputs or sidecar.resolve() in inputs:
            raise ValueError("output must not overwrite an input")
        base, base_icc = load_pass(args.base)
        texture, texture_icc = load_pass(args.texture)
        if base_icc != texture_icc:
            raise ValueError("passes must use identical colour profiles")
        # Embedded profiles need a colour-managed ingest path, not a guessed transfer.
        if base_icc:
            raise ValueError("convert profiled passes to untagged sRGB before this CLI")
        allowed = {"skin", "hair", "fabric", "protected", "confidence", "edge_guard"}
        with np.load(args.masks, allow_pickle=False) as data:
            unknown = set(data.files) - allowed
            if unknown:
                raise ValueError(f"unknown mask names: {sorted(unknown)}")
            if "confidence" not in data.files:
                raise ValueError("masks must include explicit confidence")
            masks = {name: data[name] for name in data.files}
        overrides = {key: getattr(args, key) for key in
                     ("skin", "hair", "fabric", "edge_protection")
                     if getattr(args, key) is not None}
        blend = replace(PROFILES[args.profile], **overrides)
        if args.profile == "packshot_strict" and any(
                getattr(blend, name) != 0 for name in ("skin", "hair", "fabric")):
            raise ValueError("packshot_strict does not allow generated blend")
        result, alpha = compose_regions(base, texture, blend=blend, **masks)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=args.output.parent, prefix=".reblend-") as temp:
            rendered = Path(temp) / "master.png"
            Image.fromarray(result).save(rendered)
            with Image.open(rendered) as check:
                np.testing.assert_array_equal(np.array(check), result)
            record = {
                "schema_version": 1, "operation": "region_reblend", "inference_executed": False,
                "profile": args.profile, "blend": asdict(blend), "working_space": "sRGB-linear",
                "output_encoding": "sRGB-uint8", "dimensions": [result.shape[1], result.shape[0]],
                "inputs": {name: digest(path) for name, path in
                           (("base", args.base), ("texture", args.texture), ("masks", args.masks))},
                "output_sha256": digest(rendered), "alpha_mean": float(alpha.mean()),
                "alpha_max": float(alpha.max()), "provenance": "unsigned_execution_record",
            }
            recipe = Path(temp) / "recipe.json"
            recipe.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
            os.replace(rendered, args.output)
            os.replace(recipe, sidecar)
        print(json.dumps({"output": str(args.output), "recipe": str(sidecar)}))
    except (ValueError, OSError) as error:
        parser.exit(2, f"reblend-regions: {error}\n")


if __name__ == "__main__":
    main()
