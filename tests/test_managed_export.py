"""Regression tests for F11 colour-managed, straight-alpha and 8/16-bit exports."""
from __future__ import annotations

import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest

import numpy as np
from PIL import Image, ImageCms, ImageOps

from fidelis.postprocess.managed_export import (
    compose_managed_passes,
    encode_managed_image,
    load_managed_pass,
    srgb_icc_bytes,
)
from fidelis.postprocess.regions import RegionBlend


def _custom_linear_rb_swapped_icc() -> bytes:
    """Build a valid RGB Matrix-TRC ICC profile with gamma=1.0 and swapped R/B primaries."""
    base = bytearray(srgb_icc_bytes())
    n_tags = struct.unpack(">I", base[128:132])[0]
    tags: dict[str, tuple[int, int]] = {}
    for i in range(n_tags):
        sig, off, sz = struct.unpack(">4sII", base[132 + i * 12 : 132 + (i + 1) * 12])
        tags[sig.decode("latin-1")] = (off, sz)
    ro, rs = tags["rXYZ"]
    bo, bs = tags["bXYZ"]
    r_data = bytes(base[ro : ro + rs])
    b_data = bytes(base[bo : bo + bs])
    base[ro : ro + rs] = b_data
    base[bo : bo + bs] = r_data
    for k in ("rTRC", "gTRC", "bTRC"):
        off, sz = tags[k]
        para0 = b"para\x00\x00\x00\x00\x00\x00\x00\x00" + struct.pack(">i", 65536) + b"\x00" * (sz - 16)
        base[off : off + sz] = para0
    return bytes(base)


def _encode_tiff_with_tags(
    arr: np.ndarray,
    *,
    orientation: int = 1,
    extra_sample_code: int = 2,
    icc: bytes | None = None,
) -> bytes:
    """Encode an 8-bit or 16-bit RGB/RGBA TIFF with explicit Orientation & ExtraSamples."""
    h, w, c = arr.shape
    bps = 16 if arr.dtype == np.uint16 else 8
    raw = arr.astype("<u2" if bps == 16 else np.uint8).tobytes()
    bps_bytes = struct.pack(f"<{c}H", *([bps] * c))
    n_tags = 11 + (1 if c == 4 else 0) + (1 if icc else 0)
    ifd_off = 8
    ifd_sz = 2 + n_tags * 12 + 4
    bps_off = ifd_off + ifd_sz
    extra = bytearray(bps_bytes)
    if icc:
        icc_off = bps_off + len(extra)
        extra += icc
    pix_off = bps_off + len(extra)

    def e(tag: int, typ: int, cnt: int, val: int) -> bytes:
        return struct.pack("<HHII", tag, typ, cnt, val)

    tags = [
        e(256, 4, 1, w),
        e(257, 4, 1, h),
        e(258, 3, c, bps_off),
        e(259, 3, 1, 1),
        e(262, 3, 1, 2),
        e(273, 4, 1, pix_off),
        e(274, 3, 1, orientation),
        e(277, 3, 1, c),
        e(278, 4, 1, h),
        e(279, 4, 1, len(raw)),
        e(284, 3, 1, 1),
    ]
    if c == 4:
        tags.append(e(338, 3, 1, extra_sample_code))
    if icc:
        tags.append(e(34675, 7, len(icc), icc_off))
    out = bytearray(b"II*\x00" + struct.pack("<I", ifd_off) + struct.pack("<H", len(tags)))
    for tag in tags:
        out += tag
    out += struct.pack("<I", 0) + extra + raw
    return bytes(out)


class ManagedExportTests(unittest.TestCase):
    def test_exif_orientation_normalizes_and_mismatched_dimensions_fail_closed(self) -> None:
        raw_rgba8 = np.arange(6 * 10 * 4, dtype=np.uint8).reshape(6, 10, 4)
        raw_rgba16 = raw_rgba8.astype(np.uint16) * 257

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for orient in (1, 2, 3, 5, 6, 8):
                im = Image.fromarray(raw_rgba8, mode="RGBA")
                exif = im.getexif()
                exif[274] = orient
                im.info["exif"] = exif.tobytes()
                expected8 = np.array(ImageOps.exif_transpose(im), dtype=np.uint8)

                png_path = root / f"orient_{orient}.png"
                im.save(png_path, format="PNG", exif=exif.tobytes())
                loaded_png = load_managed_pass(png_path)
                self.assertEqual(loaded_png.raw_orientation, orient)
                self.assertEqual(loaded_png.normalized_orientation, 1)
                np.testing.assert_array_equal(loaded_png.pixels, expected8)

                tif_path = root / f"orient_{orient}.tif"
                tif_path.write_bytes(_encode_tiff_with_tags(raw_rgba16, orientation=orient))
                loaded_tif = load_managed_pass(tif_path)
                self.assertEqual(loaded_tif.source_bit_depth, 16)
                self.assertEqual(loaded_tif.raw_orientation, orient)
                np.testing.assert_array_equal(loaded_tif.pixels, expected8.astype(np.uint16) * 257)

            # Orientation 6 rotates 6x10 -> 10x6; comparing with unrotated 6x10 texture must reject resizing.
            rot_path = root / "orient_6.png"
            upright_path = root / "upright.png"
            Image.fromarray(raw_rgba8, mode="RGBA").save(upright_path)
            with self.assertRaises(ValueError):
                compose_managed_passes(load_managed_pass(rot_path), load_managed_pass(upright_path))

    def test_straight_alpha_preservation_and_fail_closed_mismatches(self) -> None:
        base_arr = np.full((8, 10, 4), 200, dtype=np.uint8)
        base_arr[:2, :, 3] = 0  # transparent border with bright non-zero RGB
        base_arr[2:4, :, 3] = 128  # partial edge alpha
        base_arr[4:, :, 3] = 255
        base_arr[:, :3, :3] = [180, 90, 45]  # region later protected

        tex_rgb = np.full((8, 10, 3), 20, dtype=np.uint8)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            Image.fromarray(base_arr, mode="RGBA").save(root / "base.png")
            Image.fromarray(tex_rgb, mode="RGB").save(root / "tex.png")
            Image.fromarray(tex_rgb, mode="RGB").save(root / "base_rgb.png")
            Image.fromarray(base_arr, mode="RGBA").save(root / "tex_rgba.png")

            base_img = load_managed_pass(root / "base.png")
            tex_img = load_managed_pass(root / "tex.png")
            prot = np.zeros((8, 10), dtype=np.float32)
            prot[:, :3] = 1.0
            fabric = np.ones((8, 10), dtype=np.float32)
            conf = np.ones((8, 10), dtype=np.float32)

            out, _alpha, meta = compose_managed_passes(
                base_img,
                tex_img,
                fabric=fabric,
                protected=prot,
                confidence=conf,
                blend=RegionBlend(0.0, 0.0, 0.5),
            )
            self.assertTrue(out.has_alpha)
            self.assertEqual(meta["alpha_semantics"], "straight")
            np.testing.assert_array_equal(out.pixels[..., 3], base_arr[..., 3])
            # Zero-alpha border and protected columns must match exact base RGBA bytes.
            np.testing.assert_array_equal(out.pixels[:2, :], base_arr[:2, :])
            np.testing.assert_array_equal(out.pixels[:, :3], base_arr[:, :3])

            # Round-trip lossless 8-bit RGBA TIFF keeps ExtraSamples=2 straight alpha.
            tif_bytes = encode_managed_image(out.pixels, file_format="tiff")
            (root / "out.tif").write_bytes(tif_bytes)
            reloaded = load_managed_pass(root / "out.tif")
            np.testing.assert_array_equal(reloaded.pixels, out.pixels)

            # RGB base + RGBA texture fails closed; TIFF premultiplied ExtraSamples=1 fails closed.
            with self.assertRaises(ValueError):
                compose_managed_passes(
                    load_managed_pass(root / "base_rgb.png"),
                    load_managed_pass(root / "tex_rgba.png"),
                )
            (root / "premult.tif").write_bytes(
                _encode_tiff_with_tags(base_arr, extra_sample_code=1)
            )
            with self.assertRaises(ValueError):
                load_managed_pass(root / "premult.tif")

            # Explicit strip opt-in produces 3-channel RGB cleanly.
            stripped, _, strip_meta = compose_managed_passes(base_img, tex_img, alpha_mode="strip")
            self.assertFalse(stripped.has_alpha)
            self.assertEqual(stripped.pixels.shape, (8, 10, 3))
            self.assertEqual(strip_meta["alpha_semantics"], "none")

    def test_16bit_precision_and_no_uint16_detail_masquerading(self) -> None:
        # Step differences of 1/65535 (values 32768..32773) vanish in 8-bit, stay distinct in 16-bit.
        base16 = np.zeros((4, 6, 4), dtype=np.uint16)
        base16[..., 3] = 65535
        base16[0, :, 0] = np.array([32768, 32769, 32770, 32771, 32772, 32773], dtype=np.uint16)
        tex16 = np.full((4, 6, 4), 60000, dtype=np.uint16)
        tex16[..., 3] = 65535
        tex16[..., 0] = 32800

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "base16.png").write_bytes(encode_managed_image(base16, file_format="png"))
            (root / "tex16.png").write_bytes(encode_managed_image(tex16, file_format="png"))

            base_img = load_managed_pass(root / "base16.png")
            tex_img = load_managed_pass(root / "tex16.png")
            self.assertEqual(base_img.source_bit_depth, 16)

            prot = np.zeros((4, 6), dtype=np.float32)
            prot[:, :2] = 1.0  # first 2 columns strictly locked
            skin = np.ones((4, 6), dtype=np.float32)
            conf = np.ones((4, 6), dtype=np.float32)

            out16, _alpha, meta16 = compose_managed_passes(
                base_img, tex_img, skin=skin, protected=prot, confidence=conf, blend=RegionBlend(0.5, 0, 0)
            )
            self.assertEqual(out16.source_bit_depth, 16)
            self.assertFalse(meta16["container_precision_exceeds_source"])
            self.assertFalse(meta16["newly_recovered_source_detail"])
            np.testing.assert_array_equal(out16.pixels[:, :2], base16[:, :2])
            # Adjacent 16-bit input tones produce strictly monotonic distinct 16-bit blended values.
            row_red = out16.pixels[0, 2:, 0]
            self.assertTrue(np.all(np.diff(row_red.astype(np.int32)) >= 0))
            self.assertGreater(int(row_red[-1]), int(row_red[0]))

            # Reloading written 16-bit PNG preserves every uint16 code identically.
            (root / "out16.png").write_bytes(encode_managed_image(out16.pixels, file_format="png"))
            reloaded16 = load_managed_pass(root / "out16.png")
            np.testing.assert_array_equal(reloaded16.pixels, out16.pixels)

            # Promoting an 8-bit input into a 16-bit container discloses container_precision_exceeds_source.
            base8 = np.full((4, 6, 3), 120, dtype=np.uint8)
            Image.fromarray(base8, "RGB").save(root / "b8.png")
            b8_img = load_managed_pass(root / "b8.png")
            promoted, _, promo_meta = compose_managed_passes(b8_img, b8_img, bit_depth=16)
            self.assertEqual(promoted.source_bit_depth, 16)
            self.assertTrue(promo_meta["container_precision_exceeds_source"])
            self.assertFalse(promo_meta["newly_recovered_source_detail"])
            self.assertIn("8-bit source", promo_meta["precision_note"])

    def test_icc_management_preserves_locked_pixels_and_fails_on_invalid_icc(self) -> None:
        custom_icc = _custom_linear_rb_swapped_icc()
        base16 = np.zeros((4, 6, 4), dtype=np.uint16)
        base16[..., 3] = 65535
        base16[..., :3] = [10000, 20000, 50000]  # custom swapped R/B linear profile

        # Untagged sRGB texture: strong red in sRGB -> maps toward B in custom swapped profile.
        tex8 = np.zeros((4, 6, 3), dtype=np.uint8)
        tex8[..., :3] = [240, 60, 20]

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "base16_icc.tif").write_bytes(
                encode_managed_image(base16, icc_profile=custom_icc, file_format="tiff")
            )
            Image.fromarray(tex8, "RGB").save(root / "tex8_srgb.png")

            base_img = load_managed_pass(root / "base16_icc.tif")
            tex_img = load_managed_pass(root / "tex8_srgb.png")
            prot = np.zeros((4, 6), dtype=np.float32)
            prot[:, :3] = 1.0
            fabric = np.ones((4, 6), dtype=np.float32)
            conf = np.ones((4, 6), dtype=np.float32)

            # Policy 'preserve': converts texture at 16-bit float64 precision into base's ICC!
            preserved, _, meta_pres = compose_managed_passes(
                base_img,
                tex_img,
                fabric=fabric,
                protected=prot,
                confidence=conf,
                blend=RegionBlend(0.0, 0.0, 1.0),
                icc_policy="preserve",
            )
            self.assertEqual(preserved.icc_profile, custom_icc)
            self.assertEqual(meta_pres["icc_precision_path"]["texture"], "matrix_trc_float64")
            np.testing.assert_array_equal(preserved.pixels[:, :3], base16[:, :3])
            # Unlocked pixel received red-dominant sRGB -> blue-dominant in swapped custom ICC.
            unlocked_px = preserved.pixels[0, 4, :3]
            self.assertGreater(int(unlocked_px[2]), int(unlocked_px[0]))

            # Policy 'srgb': transforms both into canonical sRGB and embeds sRGB ICC bytes.
            srgb_out, _, meta_srgb = compose_managed_passes(
                base_img,
                tex_img,
                fabric=fabric,
                protected=prot,
                confidence=conf,
                blend=RegionBlend(0.0, 0.0, 0.5),
                icc_policy="srgb",
            )
            self.assertEqual(srgb_out.icc_profile, srgb_icc_bytes())
            self.assertEqual(meta_srgb["icc_precision_path"]["base"], "matrix_trc_float64")

            # CMYK / non-RGB ICC profile must fail closed.
            bad_icc = bytearray(srgb_icc_bytes())
            bad_icc[16:20] = b"CMYK"
            with self.assertRaises(ValueError):
                encode_managed_image(tex8, icc_profile=bytes(bad_icc), file_format="png")

    def test_default_grain_off_and_opt_in_grain_respects_protection(self) -> None:
        base = np.full((6, 8, 4), 120, dtype=np.uint8)
        base[:, :, 3] = 255
        base[:2, :, 3] = 0
        tex = np.full((6, 8, 3), 200, dtype=np.uint8)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            Image.fromarray(base, "RGBA").save(root / "base.png")
            Image.fromarray(tex, "RGB").save(root / "tex.png")
            b_img = load_managed_pass(root / "base.png")
            t_img = load_managed_pass(root / "tex.png")
            prot = np.zeros((6, 8), dtype=np.float32)
            prot[:, :3] = 1.0
            skin = np.ones((6, 8), dtype=np.float32)
            conf = np.ones((6, 8), dtype=np.float32)

            no_grain, _, m0 = compose_managed_passes(
                b_img, t_img, skin=skin, protected=prot, confidence=conf, blend=RegionBlend(0.5, 0, 0)
            )
            self.assertFalse(m0["grain_enabled"])
            self.assertEqual(m0["grain_strength"], 0.0)
            # Uniform unlocked region has zero spatial variance when default grain is off.
            self.assertEqual(int(no_grain.pixels[3:, 4:, :3].std()), 0)

            with_grain, _, mg = compose_managed_passes(
                b_img,
                t_img,
                skin=skin,
                protected=prot,
                confidence=conf,
                blend=RegionBlend(0.5, 0, 0),
                grain_strength=0.08,
                grain_seed=42,
            )
            self.assertTrue(mg["grain_enabled"])
            self.assertGreater(float(with_grain.pixels[3:, 4:, :3].std()), 0.0)
            np.testing.assert_array_equal(with_grain.pixels[:, :3], base[:, :3])
            np.testing.assert_array_equal(with_grain.pixels[:2, :], base[:2, :])

    def test_cli_export_master_end_to_end_16bit_tiff_and_png(self) -> None:
        script = Path(__file__).resolve().parents[1] / "scripts/export-master.py"
        icc = _custom_linear_rb_swapped_icc()
        # 5x7 rotated EXIF 6 -> upright 7x5
        raw_base16 = np.full((5, 7, 4), 22000, dtype=np.uint16)
        raw_base16[..., 3] = 65535
        raw_base16[:, :2, :3] = [50000, 10000, 30000]
        tex_upright = np.full((7, 5, 3), 180, dtype=np.uint8)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base_tif = root / "base.tif"
            tex_png = root / "texture.png"
            masks_npz = root / "masks.npz"
            out_png = root / "master.png"
            out_tif = root / "master.tiff"

            base_tif.write_bytes(_encode_tiff_with_tags(raw_base16, orientation=6, icc=icc))
            Image.fromarray(tex_upright, "RGB").save(tex_png)
            prot = np.zeros((7, 5), dtype=np.float32)
            prot[:2, :] = 1.0  # lock rotated top rows
            np.savez(masks_npz, fabric=np.ones((7, 5), dtype=np.float32), confidence=np.ones((7, 5), dtype=np.float32), protected=prot)

            for out_path, fmt in ((out_png, "PNG"), (out_tif, "TIFF")):
                cmd = [
                    sys.executable,
                    str(script),
                    str(base_tif),
                    str(tex_png),
                    str(out_path),
                    "--masks",
                    str(masks_npz),
                    "--profile",
                    "luxury_apparel",
                    "--icc-policy",
                    "preserve",
                ]
                proc = subprocess.run(cmd, check=True, capture_output=True, text=True)
                payload = json.loads(proc.stdout)
                recipe = json.loads(Path(payload["recipe"]).read_text(encoding="utf-8"))
                self.assertEqual(recipe["output_format"], fmt)
                self.assertEqual(recipe["output_bit_depth"], 16)
                self.assertEqual(recipe["orientation_normalized"], {"base": 6, "texture": 1, "output": 1})
                self.assertEqual(recipe["alpha_semantics"], "straight")
                self.assertFalse(recipe["grain_enabled"])
                self.assertTrue(recipe["verified_roundtrip"])
                self.assertEqual(recipe["provenance"], "unsigned_execution_record")

                reloaded = load_managed_pass(out_path)
                expected_base = np.rot90(raw_base16, k=3)
                np.testing.assert_array_equal(reloaded.pixels[:2, :], expected_base[:2, :])
                self.assertEqual(reloaded.icc_profile, icc)

            # Custom ICC file + explicit 8->16 container promotion via CLI discloses no recovered detail.
            custom_icc_file = root / "swapped.icc"
            custom_icc_file.write_bytes(icc)
            promo_png = root / "promoted.png"
            promo_cmd = [
                sys.executable,
                str(script),
                str(tex_png),
                str(tex_png),
                str(promo_png),
                "--bit-depth",
                "16",
                "--icc-policy",
                "custom",
                "--target-icc",
                str(custom_icc_file),
            ]
            promo_proc = subprocess.run(promo_cmd, check=True, capture_output=True, text=True)
            promo_recipe = json.loads(
                Path(json.loads(promo_proc.stdout)["recipe"]).read_text(encoding="utf-8")
            )
            self.assertTrue(promo_recipe["container_precision_exceeds_source"])
            self.assertFalse(promo_recipe["newly_recovered_source_detail"])
            self.assertEqual(promo_recipe["output_bit_depth"], 16)
            self.assertEqual(load_managed_pass(promo_png).icc_profile, icc)

            # Input overwrite guard must exit non-zero.
            bad = subprocess.run(
                [sys.executable, str(script), str(base_tif), str(tex_png), str(base_tif)],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(bad.returncode, 0)

    def test_png_colour_tags_trns_rejected_and_lut_profile_blends_in_srgb(self) -> None:
        from PIL.PngImagePlugin import PngInfo
        from unittest.mock import patch
        import fidelis.postprocess.managed_export as me

        arr = np.full((6, 8, 3), [120, 40, 200], dtype=np.uint8)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            # 1. RGB PNG with tRNS colour-key transparency must be rejected.
            trns_png = root / "trns_rgb.png"
            Image.fromarray(arr, "RGB").save(trns_png, format="PNG", transparency=(120, 40, 200))
            with self.assertRaisesRegex(ValueError, "tRNS"):
                load_managed_pass(trns_png)

            # 2. PNG with gAMA chunk (and no ICC / sRGB chunk) must be rejected instead of assumed sRGB.
            gama_png = root / "gama_only.png"
            info = PngInfo()
            # gAMA = 1.0 (100000 in 1/100000 units)
            info.add(b"gAMA", struct.pack(">I", 100000))
            Image.fromarray(arr, "RGB").save(gama_png, format="PNG", pnginfo=info)
            with self.assertRaisesRegex(ValueError, "gAMA/cHRM"):
                load_managed_pass(gama_png)

            # 3. LUT-backed destination profile (parse_matrix_trc_icc -> None) with allow_8bit_lut=True
            # must convert into sRGB for linear-light blending and back into the destination profile.
            swapped_icc = _custom_linear_rb_swapped_icc()
            base_px = np.zeros((4, 6, 3), dtype=np.uint8)
            base_px[:, :] = [10, 30, 220]  # in swapped_icc: strong Red in sRGB
            tex_px = np.zeros((4, 6, 3), dtype=np.uint8)
            tex_px[:, :] = [220, 30, 10]  # in sRGB: strong Red in sRGB

            base_file = root / "base_lut.png"
            tex_file = root / "tex_srgb.png"
            base_file.write_bytes(encode_managed_image(base_px, icc_profile=swapped_icc, file_format="png"))
            Image.fromarray(tex_px, "RGB").save(tex_file, format="PNG")

            base_pass = load_managed_pass(base_file)
            tex_pass = load_managed_pass(tex_file)
            skin = np.ones((4, 6), dtype=np.float32)
            conf = np.ones((4, 6), dtype=np.float32)
            prot = np.zeros((4, 6), dtype=np.float32)
            prot[:, :2] = 1.0

            orig_parse = me.parse_matrix_trc_icc

            def fake_parse_lut(icc_bytes: bytes | None):
                if icc_bytes == swapped_icc:
                    return None
                return orig_parse(icc_bytes)

            with patch.object(me, "parse_matrix_trc_icc", side_effect=fake_parse_lut):
                out_lut, _, meta_lut = compose_managed_passes(
                    base_pass,
                    tex_pass,
                    skin=skin,
                    confidence=conf,
                    protected=prot,
                    blend=RegionBlend(0.5, 0.0, 0.0),
                    icc_policy="preserve",
                    allow_8bit_lut=True,
                )

            self.assertEqual(out_lut.icc_profile, swapped_icc)
            self.assertEqual(meta_lut["icc_precision_path"]["base"], "littlecms_uint8")
            # Locked columns preserve exact base pixels in swapped_icc.
            np.testing.assert_array_equal(out_lut.pixels[:, :2], base_px[:, :2])
            # Unlocked pixels blended two red-dominant colours (in sRGB) and converted back to swapped_icc
            # where channel 2 (B slot = R primary) is dominant (> 150) and channel 0 is low (< 50).
            self.assertGreater(int(out_lut.pixels[0, 4, 2]), 150)
            self.assertLess(int(out_lut.pixels[0, 4, 0]), 50)

    def test_interior_texture_bypasses_edge_guard_in_managed_passes(self) -> None:
        base_arr = np.full((6, 9, 4), 200, dtype=np.uint8)
        base_arr[:2, :, 3] = 0
        base_arr[2:, :, 3] = 255
        tex_arr = np.full((6, 9, 3), 40, dtype=np.uint8)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            Image.fromarray(base_arr, mode="RGBA").save(root / "base.png")
            Image.fromarray(tex_arr, mode="RGB").save(root / "tex.png")
            base_img = load_managed_pass(root / "base.png")
            tex_img = load_managed_pass(root / "tex.png")

            fabric = np.ones((6, 9), dtype=np.float32)
            conf = np.ones((6, 9), dtype=np.float32)
            edge_guard = np.ones((6, 9), dtype=np.float32)
            prot = np.zeros((6, 9), dtype=np.float32)
            prot[:, :3] = 1.0
            interior = np.zeros((6, 9), dtype=np.float32)
            interior[:, 6:] = 1.0

            out, eff_alpha, _ = compose_managed_passes(
                base_img,
                tex_img,
                fabric=fabric,
                protected=prot,
                confidence=conf,
                edge_guard=edge_guard,
                interior_texture=interior,
                blend=RegionBlend(0.0, 0.0, 1.0, 0.75),
            )
            # Zero-alpha rows and protected columns remain bit-exact base
            np.testing.assert_array_equal(out.pixels[:2, :], base_arr[:2, :])
            np.testing.assert_array_equal(out.pixels[:, :3], base_arr[:, :3])
            # Hard-contour columns (rows 2:, cols 3:6) are attenuated by edge_protection
            np.testing.assert_allclose(eff_alpha[2:, 3:6], 0.25)
            # Interior texture columns (rows 2:, cols 6:) are not attenuated
            np.testing.assert_allclose(eff_alpha[2:, 6:], 1.0)
            np.testing.assert_array_equal(out.pixels[2:, 6:, :3], tex_arr[2:, 6:])


if __name__ == "__main__":
    unittest.main()
