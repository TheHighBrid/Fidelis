#!/usr/bin/env python3
"""Generate deterministic test fixtures for Fidelis visual audition classes.

Classes:
1. Portrait / exposed skin: tonal roll-off, pores, curved boundaries.
2. Fashion / fabric weave: twill/weave micro-pattern, folding luminance, seam lines.
3. Product / hard edges: sharp geometry, specular metal highlights, smooth background.
"""

from pathlib import Path
import math
import sys
from PIL import Image, ImageDraw

def create_fixtures(out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1. Portrait Skin
    # Dimensions: 256x256
    img_skin = Image.new("RGB", (256, 256), (220, 180, 160))
    draw_skin = ImageDraw.Draw(img_skin)
    # Smooth skin tonal gradient
    for y in range(256):
        r = int(235 - y * 0.25)
        g = int(190 - y * 0.22)
        b = int(170 - y * 0.20)
        draw_skin.line([(0, y), (255, y)], fill=(r, g, b))
    # Soft curved boundary (jawline / cheek)
    for x in range(256):
        arc_y = int(160 + 40 * math.sin(x * math.pi / 256))
        for y in range(arc_y, 256):
            orig = img_skin.getpixel((x, y))
            draw_skin.point((x, y), fill=(int(orig[0] * 0.75), int(orig[1] * 0.72), int(orig[2] * 0.70)))
    # Micro-texture (simulated pore noise with deterministic seed)
    pixels_skin = img_skin.load()
    import random
    rng = random.Random(42)
    for y in range(256):
        for x in range(256):
            if y < 160:
                noise = rng.randint(-5, 5)
                r, g, b = pixels_skin[x, y]
                pixels_skin[x, y] = (
                    max(0, min(255, r + noise)),
                    max(0, min(255, g + noise)),
                    max(0, min(255, b + noise)),
                )
    img_skin.save(out_dir / "portrait_skin.png")
    print(f"Created: {out_dir / 'portrait_skin.png'}")

    # 2. Fabric Weave
    img_fabric = Image.new("RGB", (256, 256), (40, 50, 75))
    pixels_fabric = img_fabric.load()
    for y in range(256):
        # Global fold luminance variation
        fold = math.sin(x_fold := y / 30.0) * 20.0
        for x in range(256):
            # Twill diagonal weave pattern (2x2 repeated structure)
            twill = 15 if ((x + y) % 4 < 2) else -15
            # Thread grain
            thread = 8 if (x % 2 == 0) else -8
            base_r, base_g, base_b = 45, 55, 85
            val_r = int(max(0, min(255, base_r + fold + twill + thread)))
            val_g = int(max(0, min(255, base_g + fold + twill + thread)))
            val_b = int(max(0, min(255, base_b + fold + twill + thread)))
            pixels_fabric[x, y] = (val_r, val_g, val_b)
    # Add a stitched seam across the fabric
    draw_fabric = ImageDraw.Draw(img_fabric)
    for x in range(10, 246, 12):
        draw_fabric.line([(x, 120), (x + 6, 120)], fill=(200, 180, 140), width=2)
    draw_fabric.line([(0, 117), (255, 117)], fill=(20, 25, 40), width=1)
    draw_fabric.line([(0, 123), (255, 123)], fill=(20, 25, 40), width=1)
    img_fabric.save(out_dir / "fabric_weave.png")
    print(f"Created: {out_dir / 'fabric_weave.png'}")

    # 3. Product Hard Edges
    # Perfectly smooth neutral background
    img_product = Image.new("RGB", (256, 256), (240, 240, 242))
    draw_product = ImageDraw.Draw(img_product)
    # Metallic hardware element (cylinder / zipper pull)
    for x in range(60, 196):
        # Metallic gradient highlight
        t = (x - 60) / 136.0
        lum = int(80 + 150 * math.sin(t * math.pi)**2)
        draw_product.line([(x, 60), (x, 150)], fill=(lum, lum, lum + 5), width=1)
    # Beveled edge
    draw_product.rectangle([(58, 58), (198, 152)], outline=(50, 50, 55), width=2)
    # Crisp typography / brand geometry
    draw_product.rectangle([(90, 95), (166, 115)], fill=(30, 30, 32))
    draw_product.text((100, 100), "FIDELIS", fill=(250, 250, 250))
    img_product.save(out_dir / "product_hard_edges.png")
    print(f"Created: {out_dir / 'product_hard_edges.png'}")

if __name__ == "__main__":
    target = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
    if len(sys.argv) > 1:
        target = Path(sys.argv[1])
    create_fixtures(target)
