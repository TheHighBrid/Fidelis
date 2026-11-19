#!/usr/bin/env python3
"""Generate deterministic synthetic fixtures for photographic protocol CI tests.

These images are NOT the production rights-cleared corpus. They exist only to
prove the protocol flags plastic skin, exaggerated texture, invented product
detail, and lettering mutation.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont


def _rng(seed: int) -> np.random.Generator:
    return np.random.default_rng(seed)


def make_skin_base(path: Path, size: int = 128) -> None:
    rng = _rng(11)
    yy, xx = np.mgrid[0:size, 0:size]
    base = np.stack(
        [
            190 + 20 * np.sin(xx / 18.0) + 8 * np.sin(yy / 11.0),
            145 + 15 * np.sin(xx / 22.0),
            120 + 12 * np.cos(yy / 16.0),
        ],
        axis=-1,
    )
    grain = rng.normal(0.0, 4.5, size=(size, size, 1))
    pores = (rng.random((size, size)) < 0.02).astype(np.float32) * -12.0
    rgb = np.clip(base + grain + pores[:, :, None], 0, 255).astype(np.uint8)
    Image.fromarray(rgb, mode="RGB").save(path)


def make_skin_plastic(base_path: Path, out_path: Path) -> None:
    img = Image.open(base_path).convert("RGB")
    # Heavy smooth + mild unsharp: classic plastic + fake crispness.
    smooth = img.filter(ImageFilter.GaussianBlur(radius=2.8))
    sharp = smooth.filter(ImageFilter.UnsharpMask(radius=2, percent=180, threshold=2))
    sharp.save(out_path)


def make_skin_good(base_path: Path, out_path: Path) -> None:
    img = Image.open(base_path).convert("RGB")
    # Mild denoise that preserves mid-band grain approximately.
    mild = img.filter(ImageFilter.GaussianBlur(radius=0.4))
    arr = np.asarray(mild, dtype=np.float32)
    base = np.asarray(img, dtype=np.float32)
    blended = np.clip(0.7 * base + 0.3 * arr, 0, 255).astype(np.uint8)
    Image.fromarray(blended, mode="RGB").save(out_path)


def make_textile_base(path: Path, size: int = 128) -> None:
    rng = _rng(23)
    yy, xx = np.mgrid[0:size, 0:size]
    weave = 140 + 35 * np.sin(xx / 3.0) * np.sin(yy / 3.5)
    rgb = np.stack([weave, weave * 0.92, weave * 0.75], axis=-1)
    rgb = np.clip(rgb + rng.normal(0, 3.0, rgb.shape), 0, 255).astype(np.uint8)
    Image.fromarray(rgb, mode="RGB").save(path)


def make_textile_hallucinated(base_path: Path, out_path: Path) -> None:
    img = Image.open(base_path).convert("RGB")
    arr = np.asarray(img, dtype=np.float32)
    size = arr.shape[0]
    yy, xx = np.mgrid[0:size, 0:size]
    checker = ((xx // 4 + yy // 4) % 2) * 40.0 - 20.0
    out = np.clip(arr + checker[:, :, None], 0, 255).astype(np.uint8)
    # Extra unsharp to look "detailed".
    Image.fromarray(out, mode="RGB").filter(ImageFilter.UnsharpMask(radius=1.5, percent=250, threshold=1)).save(out_path)


def make_product_base(path: Path, size: int = 128) -> None:
    img = Image.new("RGB", (size, size), (235, 235, 238))
    draw = ImageDraw.Draw(img)
    draw.rectangle([24, 24, 104, 104], outline=(40, 40, 45), width=3)
    draw.line([24, 64, 104, 64], fill=(60, 60, 70), width=2)
    draw.ellipse([56, 56, 72, 72], outline=(30, 30, 35), width=2)
    img.save(path)


def make_product_invented(base_path: Path, out_path: Path) -> None:
    img = Image.open(base_path).convert("RGB")
    draw = ImageDraw.Draw(img)
    # Invent hardware and a fake logo glyph not present in base.
    draw.rectangle([80, 30, 96, 46], fill=(20, 20, 25))
    draw.text((32, 78), "X", fill=(10, 10, 10))
    img.filter(ImageFilter.UnsharpMask(radius=2, percent=200, threshold=0)).save(out_path)



def make_hair_base(path: Path, size: int = 128) -> None:
    yy, xx = np.mgrid[0:size, 0:size]
    base = 40 + 10 * np.sin(xx / 40.0)
    strands = (np.sin(yy / 2.0 + xx / 18.0) > 0.6).astype(np.float32) * 90
    rgb = np.clip(
        np.stack([base + strands * 0.7, base + strands * 0.5, base + strands * 0.3], axis=-1),
        0,
        255,
    ).astype(np.uint8)
    Image.fromarray(rgb, mode="RGB").save(path)


def make_hair_exaggerated(base_path: Path, out_path: Path) -> None:
    arr = np.asarray(Image.open(base_path).convert("RGB"), dtype=np.float32)
    rng = _rng(9)
    noise = rng.integers(0, 140, arr.shape).astype(np.float32)
    mask = (np.sin(np.arange(arr.shape[1])[None, :] / 0.8) + 1) / 2
    out = np.clip(arr + noise * mask[:, :, None] * 0.9, 0, 255).astype(np.uint8)
    Image.fromarray(out, mode="RGB").filter(
        ImageFilter.UnsharpMask(radius=2.5, percent=300, threshold=0)
    ).save(out_path)

def make_lettering_base(path: Path, size: int = 128) -> None:
    img = Image.new("RGB", (size, size), (245, 245, 245))
    draw = ImageDraw.Draw(img)
    draw.text((18, 48), "MELATO", fill=(20, 20, 20))
    img.save(path)


def make_lettering_mutated(base_path: Path, out_path: Path) -> None:
    img = Image.open(base_path).convert("RGB")
    draw = ImageDraw.Draw(img)
    # Overwrite with different glyph geometry while looking sharp.
    draw.rectangle([14, 40, 118, 88], fill=(245, 245, 245))
    draw.text((18, 48), "MEIATO", fill=(0, 0, 0))
    img.filter(ImageFilter.SHARPEN).save(out_path)


def make_lettering_good(base_path: Path, out_path: Path) -> None:
    img = Image.open(base_path).convert("RGB")
    # Tiny contrast lift without rewriting glyphs.
    arr = np.asarray(img, dtype=np.float32)
    out = np.clip((arr - 128.0) * 1.05 + 128.0, 0, 255).astype(np.uint8)
    Image.fromarray(out, mode="RGB").save(out_path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "photographic_protocol",
    )
    args = parser.parse_args()
    out: Path = args.out_dir
    out.mkdir(parents=True, exist_ok=True)

    skin_base = out / "skin_base.png"
    make_skin_base(skin_base)
    make_skin_plastic(skin_base, out / "skin_plastic.png")
    make_skin_good(skin_base, out / "skin_good.png")

    textile_base = out / "textile_base.png"
    make_textile_base(textile_base)
    make_textile_hallucinated(textile_base, out / "textile_hallucinated.png")

    product_base = out / "product_base.png"
    make_product_base(product_base)
    make_product_invented(product_base, out / "product_invented.png")

    hair_base = out / "hair_base.png"
    make_hair_base(hair_base)
    make_hair_exaggerated(hair_base, out / "hair_exaggerated.png")

    letter_base = out / "lettering_base.png"
    make_lettering_base(letter_base)
    make_lettering_mutated(letter_base, out / "lettering_mutated.png")
    make_lettering_good(letter_base, out / "lettering_good.png")

    manifest = out / "FIXTURE_README.md"
    manifest.write_text(
        "# Photographic protocol synthetic fixtures\n\n"
        "Deterministic CI fixtures for Bot 05 protocol regressions.\n\n"
        "**Not** the production rights-cleared 60-case corpus.\n"
        "**Not** licensed fashion/portrait photography.\n"
        "Do not cite these as quality evidence for release gates.\n",
        encoding="utf-8",
    )
    print(f"Wrote synthetic protocol fixtures to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
