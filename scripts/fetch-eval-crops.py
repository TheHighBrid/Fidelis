#!/usr/bin/env python3
"""Curate standardized real-world photographic evaluation crops for Fidelis.

Classes:
1. `portrait_skin_real.png`: Photographic skin tones, eyes, hair boundaries, and pore transitions.
2. `fashion_fabric_real.png`: Textile weave, embroidery patch, uniform folds, and garment stitching.
3. `product_edges_real.png`: Hard metallic reflection, ceramic curves, specular highlights, and edge contrast.

Sourced from the public domain standard imaging dataset (NASA astronaut portrait / photographic stills).
Outputs verified PNG crops to `experiments/eval_crops/`.
"""

import argparse
import hashlib
from pathlib import Path
from PIL import Image

def curate_eval_crops(target_dir: Path):
    from skimage import data

    target_dir.mkdir(parents=True, exist_ok=True)
    print(f"Curating real-world Fidelis evaluation crops into: {target_dir}")

    # 1. Portrait Skin Crop (Astronaut Eileen Collins face)
    astro = data.astronaut()
    im_astro = Image.fromarray(astro)
    skin_crop = im_astro.crop((160, 40, 310, 190))
    p_skin = target_dir / "portrait_skin_real.png"
    skin_crop.save(p_skin)
    sha_skin = hashlib.sha256(p_skin.read_bytes()).hexdigest()
    print(f"  [Portrait / Skin]  {p_skin.name:<25} {skin_crop.width}x{skin_crop.height}  SHA-256: {sha_skin[:16]}...")

    # 2. Fabric / Textile Crop (NASA patch, uniform collar, knit texture)
    fabric_crop = im_astro.crop((80, 300, 280, 500))
    p_fabric = target_dir / "fashion_fabric_real.png"
    fabric_crop.save(p_fabric)
    sha_fabric = hashlib.sha256(p_fabric.read_bytes()).hexdigest()
    print(f"  [Fashion / Fabric] {p_fabric.name:<25} {fabric_crop.width}x{fabric_crop.height}  SHA-256: {sha_fabric[:16]}...")

    # 3. Product / Hard Edges Crop (Ceramic, metallic reflections, spoon hardware)
    coffee = data.coffee()
    im_coffee = Image.fromarray(coffee)
    product_crop = im_coffee.crop((200, 100, 450, 350))
    p_product = target_dir / "product_edges_real.png"
    product_crop.save(p_product)
    sha_product = hashlib.sha256(p_product.read_bytes()).hexdigest()
    print(f"  [Product / Edges]  {p_product.name:<25} {product_crop.width}x{product_crop.height}  SHA-256: {sha_product[:16]}...")

    print("\nDataset ready for multi-model audition and VOSR quality sweeps.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Curate photographic evaluation crops for Fidelis.")
    parser.add_argument("-d", "--dir", type=Path, default=Path("experiments/eval_crops"), help="Target directory")
    args = parser.parse_args()
    curate_eval_crops(args.dir)
