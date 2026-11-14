#!/usr/bin/env python3
"""Colour-managed, EXIF-normalized, straight-alpha and 8/16-bit master export CLI."""
import argparse
from dataclasses import replace
import json
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fidelis.postprocess.managed_export import (
    ALPHA_MODES,
    ICC_POLICIES,
    INTENTS,
    compose_managed_passes,
    export_verified_master,
    load_managed_pass,
)
from fidelis.postprocess.regions import PROFILES


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base", type=Path, help="Normalized or raw precision base PNG/TIFF")
    parser.add_argument("texture", type=Path, help="Aligned texture candidate PNG/TIFF")
    parser.add_argument("output", type=Path, help="Output master path (.png, .tif, or .tiff)")
    parser.add_argument(
        "--masks",
        type=Path,
        default=None,
        help="Optional NPZ with skin/hair/fabric/protected/confidence/edge_guard masks",
    )
    parser.add_argument("--profile", choices=PROFILES, default="luxury_apparel")
    for name in ("skin", "hair", "fabric", "edge-protection"):
        parser.add_argument("--" + name, type=float)
    parser.add_argument(
        "--bit-depth",
        choices=("auto", "8", "16"),
        default="auto",
        help="Export precision; auto preserves highest input bit depth without inflating 8-bit as recovered detail",
    )
    parser.add_argument("--icc-policy", choices=sorted(ICC_POLICIES), default="preserve")
    parser.add_argument("--target-icc", type=Path, default=None, help="Target ICC profile for --icc-policy custom")
    parser.add_argument("--icc-intent", choices=sorted(INTENTS), default="relative_colorimetric")
    parser.add_argument("--alpha-mode", choices=sorted(ALPHA_MODES), default="preserve_base")
    parser.add_argument(
        "--grain-strength",
        type=float,
        default=0.0,
        help="Explicit opt-in luma grain in [0.0, 0.25]; default 0.0 (off)",
    )
    parser.add_argument("--grain-seed", type=int, default=0)
    parser.add_argument(
        "--allow-8bit-lut",
        action="store_true",
        help="Explicitly permit 8-bit LittleCMS fallback for 16-bit non-matrix LUT ICC transforms",
    )
    args = parser.parse_args()

    try:
        base_img = load_managed_pass(args.base)
        tex_img = load_managed_pass(args.texture)
        input_paths = {"base": args.base, "texture": args.texture}

        masks = {}
        if args.masks is not None:
            input_paths["masks"] = args.masks
            allowed = {"skin", "hair", "fabric", "protected", "confidence", "edge_guard"}
            with np.load(args.masks, allow_pickle=False) as data:
                unknown = set(data.files) - allowed
                if unknown:
                    raise ValueError(f"unknown mask names: {sorted(unknown)}")
                if "confidence" not in data.files:
                    raise ValueError("masks must include explicit confidence")
                masks = {name: data[name] for name in data.files}

        target_icc_bytes = None
        if args.target_icc is not None:
            input_paths["target_icc"] = args.target_icc
            target_icc_bytes = args.target_icc.read_bytes()

        overrides = {
            key: getattr(args, key)
            for key in ("skin", "hair", "fabric", "edge_protection")
            if getattr(args, key) is not None
        }
        blend = replace(PROFILES[args.profile], **overrides)
        if args.profile == "packshot_strict" and any(
            getattr(blend, name) != 0 for name in ("skin", "hair", "fabric")
        ):
            raise ValueError("packshot_strict does not allow generated blend")

        composed, _alpha, metadata = compose_managed_passes(
            base_img,
            tex_img,
            blend=blend,
            icc_policy=args.icc_policy,
            target_icc=target_icc_bytes,
            icc_intent=args.icc_intent,
            alpha_mode=args.alpha_mode,
            bit_depth=args.bit_depth,
            grain_strength=args.grain_strength,
            grain_seed=args.grain_seed,
            allow_8bit_lut=args.allow_8bit_lut,
            **masks,
        )
        out_path, sidecar_path, _record = export_verified_master(
            args.output,
            composed,
            metadata,
            input_paths=input_paths,
            profile=args.profile,
        )
        print(json.dumps({"output": str(out_path), "recipe": str(sidecar_path)}))
    except (ValueError, OSError) as error:
        parser.exit(2, f"export-master: {error}\n")


if __name__ == "__main__":
    main()
