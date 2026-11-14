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

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fidelis.postprocess.regions import PROFILES, _mask, compose_regions
from fidelis.studio.png import read_export_pass, write_rgb_png


def digest(path):
    h = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


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
    parser.add_argument("--depth", type=int, choices=(8, 16),
                        help="Output depth; default retains the highest input depth")
    parser.add_argument("--convert-icc", action="store_true",
                        help="Convert embedded 8-bit RGB profiles to the sRGB working space")
    args = parser.parse_args()
    try:
        if args.output.suffix.lower() != ".png":
            raise ValueError("output must be a PNG file")
        sidecar = args.output.with_suffix(".png.recipe.json")
        inputs = {p.resolve() for p in (args.base, args.texture, args.masks)}
        if args.output.resolve() in inputs or sidecar.resolve() in inputs:
            raise ValueError("output must not overwrite an input")
        base, base_converted = read_export_pass(args.base, allow_alpha=True, convert_icc=args.convert_icc)
        texture, texture_converted = read_export_pass(args.texture, convert_icc=args.convert_icc)
        depth = args.depth or 8 * max(base.dtype.itemsize, texture.dtype.itemsize)
        if depth < 8 * max(base.dtype.itemsize, texture.dtype.itemsize):
            raise ValueError("Output depth would discard input precision")
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
        if base.shape[2] == 4:
            if base.shape[:2] != texture.shape[:2]:
                raise ValueError("passes must have identical dimensions; no implicit resizing")
            transparent = base[:, :, 3] == 0
            protection = masks.get("protected")
            if protection is not None:
                protection = _mask(protection, base.shape[:2], "protected")
            masks["protected"] = np.maximum(transparent, protection) if protection is not None else transparent.astype(np.float32)
        dtype = np.uint16 if depth == 16 else np.uint8
        result, alpha = compose_regions(base[:, :, :3], texture, blend=blend, output_dtype=dtype, **masks)
        if base.shape[2] == 4:
            opacity = base[:, :, 3].astype(dtype) * (np.iinfo(dtype).max // np.iinfo(base.dtype).max)
            result = np.dstack((result, opacity))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=args.output.parent, prefix=".reblend-") as temp:
            rendered = Path(temp) / "master.png"
            with rendered.open("wb") as stream:
                write_rgb_png(result, stream)
            check, _ = read_export_pass(rendered, allow_alpha=True)
            if not np.array_equal(check, result):
                raise ValueError("Export failed pixel-exact round-trip verification")
            record = {
                "schema_version": 1, "operation": "region_reblend", "inference_executed": False,
                "profile": args.profile, "blend": asdict(blend), "working_space": "sRGB-linear",
                "output_encoding": f"sRGB-uint{depth}", "dimensions": [result.shape[1], result.shape[0]],
                "input_depths": {"base": base.dtype.itemsize * 8, "texture": texture.dtype.itemsize * 8},
                "icc_converted": {"base": base_converted, "texture": texture_converted},
                "opacity": "base-straight-alpha" if result.shape[2] == 4 else "opaque",
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
