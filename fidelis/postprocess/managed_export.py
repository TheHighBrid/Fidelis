"""Colour-managed, EXIF-normalized, alpha-safe and 8/16-bit precision export.

This module extends the standalone RGB8 composition path in ``regions.py`` to:
- explicit EXIF orientation (1..8) normalization without silent resizing,
- straight-alpha preservation (RGBA) without premultiplied edge halos,
- deliberate ICC profile validation and transform via LittleCMS / matrix-TRC,
- true float64 linear-light blending and 8-bit or 16-bit PNG/TIFF exports,
- truthful container bit-depth metadata so uint16 wrappers never masquerade
  as newly recovered detail, and zero default synthetic grain.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import io
import math
import os
from pathlib import Path
import struct
import tempfile
from typing import Optional
import zlib

import cv2
import numpy as np
from PIL import Image, ImageCms

from fidelis.postprocess.regions import PROFILES, RegionBlend, _mask

VALID_ORIENTATIONS = frozenset(range(1, 9))
INTENTS = {
    "perceptual": ImageCms.Intent.PERCEPTUAL,
    "relative_colorimetric": ImageCms.Intent.RELATIVE_COLORIMETRIC,
    "saturation": ImageCms.Intent.SATURATION,
    "absolute_colorimetric": ImageCms.Intent.ABSOLUTE_COLORIMETRIC,
}
ICC_POLICIES = frozenset({"preserve", "srgb", "custom"})
ALPHA_MODES = frozenset({"preserve_base", "strip"})
SUPPORTED_EXTENSIONS = {".png": "png", ".tif": "tiff", ".tiff": "tiff"}


@dataclass(frozen=True)
class ManagedImage:
    """In-memory normalized RGB/RGBA pass with explicit provenance."""

    pixels: np.ndarray
    source_bit_depth: int
    has_alpha: bool
    icc_profile: Optional[bytes]
    icc_description: str
    raw_orientation: int
    normalized_orientation: int
    source_format: str


@dataclass(frozen=True)
class _TrcCurve:
    """1D ICC tone reproduction curve (para types 0..4 or curv)."""

    kind: str  # "gamma" | "para" | "lut"
    params: tuple[float, ...]
    lut: Optional[np.ndarray] = None

    def to_linear(self, x: np.ndarray) -> np.ndarray:
        x = np.clip(np.asarray(x, dtype=np.float64), 0.0, 1.0)
        if self.kind == "gamma":
            g = self.params[0]
            return np.ones_like(x) if g == 0.0 else np.power(x, g)
        if self.kind == "lut":
            assert self.lut is not None
            grid = np.linspace(0.0, 1.0, len(self.lut), dtype=np.float64)
            return np.interp(x, grid, self.lut)
        return _eval_para_forward(x, self.params)

    def from_linear(self, y: np.ndarray) -> np.ndarray:
        y = np.clip(np.asarray(y, dtype=np.float64), 0.0, 1.0)
        if self.kind == "gamma":
            g = self.params[0]
            return np.ones_like(y) if g == 0.0 else np.power(y, 1.0 / g)
        if self.kind == "lut":
            assert self.lut is not None
            grid = np.linspace(0.0, 1.0, len(self.lut), dtype=np.float64)
            return np.interp(y, self.lut, grid)
        return _eval_para_inverse(y, self.params)


@dataclass(frozen=True)
class _MatrixTrcProfile:
    matrix: np.ndarray  # 3x3 columns = [rXYZ, gXYZ, bXYZ] in D50 PCS
    inv_matrix: np.ndarray
    trcs: tuple[_TrcCurve, _TrcCurve, _TrcCurve]


def _eval_para_forward(x: np.ndarray, params: tuple[float, ...]) -> np.ndarray:
    ftype = int(params[0])
    if ftype == 0:
        g = params[1]
        return np.power(x, g)
    if ftype == 1:
        g, a, b = params[1:4]
        thr = -b / a if a != 0 else 1.0
        return np.where(x >= thr, np.power(np.maximum(a * x + b, 0.0), g), 0.0)
    if ftype == 2:
        g, a, b, c = params[1:5]
        thr = -b / a if a != 0 else 1.0
        return np.where(x >= thr, np.power(np.maximum(a * x + b, 0.0), g) + c, c)
    if ftype == 3:
        g, a, b, c, d = params[1:6]
        return np.where(x >= d, np.power(np.maximum(a * x + b, 0.0), g), c * x)
    g, a, b, c, d, e, f = params[1:8]
    return np.where(x >= d, np.power(np.maximum(a * x + b, 0.0), g) + e, c * x + f)


def _eval_para_inverse(y: np.ndarray, params: tuple[float, ...]) -> np.ndarray:
    ftype = int(params[0])
    if ftype == 0:
        g = params[1]
        return np.power(y, 1.0 / g)
    if ftype == 1:
        g, a, b = params[1:4]
        return np.clip((np.power(y, 1.0 / g) - b) / a, 0.0, 1.0)
    if ftype == 2:
        g, a, b, c = params[1:5]
        return np.where(y > c, np.clip((np.power(np.maximum(y - c, 0.0), 1.0 / g) - b) / a, 0.0, 1.0), 0.0)
    if ftype == 3:
        g, a, b, c, d = params[1:6]
        y_thr = c * d
        return np.where(
            y >= y_thr,
            (np.power(np.maximum(y, 0.0), 1.0 / g) - b) / a,
            y / c if c != 0 else 0.0,
        )
    g, a, b, c, d, e, f = params[1:8]
    y_thr = c * d + f
    return np.where(
        y >= y_thr,
        (np.power(np.maximum(y - e, 0.0), 1.0 / g) - b) / a,
        (y - f) / c if c != 0 else 0.0,
    )


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def srgb_icc_bytes() -> bytes:
    """Return canonical sRGB ICC profile bytes embedded by LittleCMS/Pillow."""
    return ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()


def validate_icc_profile(icc_bytes: bytes) -> str:
    """Validate an RGB ICC profile buffer and return its human description."""
    if not isinstance(icc_bytes, (bytes, bytearray)) or len(icc_bytes) < 132:
        raise ValueError("ICC profile buffer is missing or truncated")
    raw = bytes(icc_bytes)
    if raw[36:40] != b"acsp":
        raise ValueError("invalid ICC profile signature (expected 'acsp')")
    if raw[16:20] != b"RGB ":
        space = raw[16:20].decode("latin-1", errors="replace").strip()
        raise ValueError(f"unsupported ICC colour space {space!r}; only RGB profiles are supported")
    try:
        prof = ImageCms.ImageCmsProfile(io.BytesIO(raw))
        desc = ImageCms.getProfileDescription(prof).strip() or "embedded-RGB-ICC"
        return desc
    except Exception as exc:
        raise ValueError(f"invalid ICC profile: {exc}") from exc


def _parse_trc_tag(raw: bytes, offset: int, size: int) -> Optional[_TrcCurve]:
    if offset + size > len(raw) or size < 12:
        return None
    sig = raw[offset : offset + 4]
    if sig == b"curv":
        count = struct.unpack(">I", raw[offset + 8 : offset + 12])[0]
        if count == 0:
            return _TrcCurve("gamma", (1.0,))
        if count == 1 and size >= 14:
            gamma = struct.unpack(">H", raw[offset + 12 : offset + 14])[0] / 256.0
            return _TrcCurve("gamma", (gamma,))
        if count > 1 and size >= 12 + count * 2:
            vals = np.frombuffer(raw[offset + 12 : offset + 12 + count * 2], dtype=">u2")
            return _TrcCurve("lut", (), vals.astype(np.float64) / 65535.0)
        return None
    if sig == b"para" and size >= 16:
        ftype = struct.unpack(">H", raw[offset + 8 : offset + 10])[0]
        expected_counts = {0: 1, 1: 3, 2: 4, 3: 5, 4: 7}
        n_params = expected_counts.get(ftype)
        if n_params is None or size < 12 + n_params * 4:
            return None
        params = tuple(
            struct.unpack(">i", raw[offset + 12 + i * 4 : offset + 16 + i * 4])[0] / 65536.0
            for i in range(n_params)
        )
        return _TrcCurve("para", (float(ftype),) + params)
    return None


def parse_matrix_trc_icc(icc_bytes: Optional[bytes]) -> Optional[_MatrixTrcProfile]:
    """Parse standard D50-adapted RGB Matrix/TRC ICC profile if supported."""
    raw = srgb_icc_bytes() if icc_bytes is None else bytes(icc_bytes)
    if len(raw) < 132 or raw[36:40] != b"acsp" or raw[16:20] != b"RGB ":
        return None
    n_tags = struct.unpack(">I", raw[128:132])[0]
    if 132 + n_tags * 12 > len(raw):
        return None
    tags: dict[str, tuple[int, int]] = {}
    for i in range(n_tags):
        sig, off, sz = struct.unpack(">4sII", raw[132 + i * 12 : 132 + (i + 1) * 12])
        tags[sig.decode("latin-1")] = (off, sz)
    if any(k in tags for k in ("A2B0", "B2A0")):
        return None
    required = ("rXYZ", "gXYZ", "bXYZ", "rTRC", "gTRC", "bTRC")
    if not all(k in tags for k in required):
        return None

    cols = []
    for k in ("rXYZ", "gXYZ", "bXYZ"):
        off, sz = tags[k]
        if sz < 20 or off + sz > len(raw) or raw[off : off + 4] != b"XYZ ":
            return None
        vec = [
            struct.unpack(">i", raw[off + 8 + j * 4 : off + 12 + j * 4])[0] / 65536.0
            for j in range(3)
        ]
        cols.append(vec)
    matrix = np.column_stack(cols).astype(np.float64)
    try:
        inv_matrix = np.linalg.inv(matrix)
    except np.linalg.LinAlgError:
        return None

    trcs = []
    for k in ("rTRC", "gTRC", "bTRC"):
        off, sz = tags[k]
        trc = _parse_trc_tag(raw, off, sz)
        if trc is None:
            return None
        trcs.append(trc)
    return _MatrixTrcProfile(matrix=matrix, inv_matrix=inv_matrix, trcs=(trcs[0], trcs[1], trcs[2]))


def _linearize_rgb(rgb01: np.ndarray, prof: _MatrixTrcProfile) -> np.ndarray:
    out = np.empty_like(rgb01, dtype=np.float64)
    for ch in range(3):
        out[..., ch] = prof.trcs[ch].to_linear(rgb01[..., ch])
    return out


def _encode_rgb(lin01: np.ndarray, prof: _MatrixTrcProfile) -> np.ndarray:
    out = np.empty_like(lin01, dtype=np.float64)
    for ch in range(3):
        out[..., ch] = prof.trcs[ch].from_linear(lin01[..., ch])
    return np.clip(out, 0.0, 1.0)


def convert_icc_pixels(
    pixels: np.ndarray,
    src_icc: Optional[bytes],
    dst_icc: Optional[bytes],
    *,
    intent: str = "relative_colorimetric",
    allow_8bit_lut: bool = False,
) -> tuple[np.ndarray, str]:
    """Convert RGB or straight-RGBA pixels cleanly between ICC profiles.

    Alpha (channel 3, when present) is preserved unmodified. When src or dst is
    None, canonical sRGB is used explicitly for the transform step.
    """
    if intent not in INTENTS:
        raise ValueError(f"unsupported ICC intent {intent!r}; choose from {sorted(INTENTS)}")
    effective_src = srgb_icc_bytes() if src_icc is None else src_icc
    effective_dst = srgb_icc_bytes() if dst_icc is None else dst_icc
    if effective_src == effective_dst:
        return pixels.copy(), "identity"

    src_mt = parse_matrix_trc_icc(effective_src)
    dst_mt = parse_matrix_trc_icc(effective_dst)
    is_u16 = pixels.dtype == np.uint16
    max_val = 65535.0 if is_u16 else 255.0

    if src_mt is not None and dst_mt is not None and intent == "relative_colorimetric":
        rgb01 = pixels[..., :3].astype(np.float64) / max_val
        lin_src = _linearize_rgb(rgb01, src_mt)
        xyz = np.einsum("ij,hwj->hwi", src_mt.matrix, lin_src)
        lin_dst = np.einsum("ij,hwj->hwi", dst_mt.inv_matrix, xyz)
        enc_dst = _encode_rgb(lin_dst, dst_mt)
        rgb_out = np.clip(np.rint(enc_dst * max_val), 0, max_val).astype(pixels.dtype)
        if pixels.shape[2] == 4:
            out = np.concatenate([rgb_out, pixels[..., 3:4]], axis=2)
        else:
            out = rgb_out
        return out, "matrix_trc_float64"

    if is_u16 and not allow_8bit_lut:
        raise ValueError(
            "16-bit cross-profile LUT/intent conversion requires allow_8bit_lut=True "
            "to avoid silently quantizing 16-bit precision via 8-bit LittleCMS"
        )

    src_prof = ImageCms.ImageCmsProfile(io.BytesIO(effective_src))
    dst_prof = ImageCms.ImageCmsProfile(io.BytesIO(effective_dst))
    mode = "RGBA" if pixels.shape[2] == 4 else "RGB"
    u8_in = (
        np.clip(np.rint(pixels.astype(np.float64) / 257.0), 0, 255).astype(np.uint8)
        if is_u16
        else pixels
    )
    im_out = ImageCms.profileToProfile(
        Image.fromarray(u8_in, mode=mode),
        src_prof,
        dst_prof,
        renderingIntent=INTENTS[intent],
        outputMode=mode,
    )
    arr_out = np.array(im_out, dtype=np.uint8)
    if is_u16:
        # Preserve original 16-bit alpha untouched while promoting RGB cleanly.
        rgb16 = (arr_out[..., :3].astype(np.uint16)) * 257
        out = np.concatenate([rgb16, pixels[..., 3:4]], axis=2) if pixels.shape[2] == 4 else rgb16
        return out, "littlecms_uint8_lut_promoted"
    return arr_out, "littlecms_uint8"


def normalize_exif_orientation(pixels: np.ndarray, orientation: int) -> np.ndarray:
    """Normalize pixel orientation (EXIF tags 1..8) matching ImageOps.exif_transpose."""
    if orientation not in VALID_ORIENTATIONS:
        raise ValueError(f"unsupported EXIF orientation {orientation!r}; expected 1..8")
    if orientation == 1:
        return pixels.copy()
    if orientation == 2:
        return np.ascontiguousarray(pixels[:, ::-1])
    if orientation == 3:
        return np.ascontiguousarray(pixels[::-1, ::-1])
    if orientation == 4:
        return np.ascontiguousarray(pixels[::-1, :])
    if orientation == 5:
        return np.ascontiguousarray(np.swapaxes(pixels, 0, 1))
    if orientation == 6:
        return np.ascontiguousarray(np.rot90(pixels, k=3))
    if orientation == 7:
        return np.ascontiguousarray(np.swapaxes(pixels, 0, 1)[::-1, ::-1])
    return np.ascontiguousarray(np.rot90(pixels, k=1))


def _read_png_header(path: Path) -> tuple[int, int, set[bytes]]:
    data = path.read_bytes()
    if not data.startswith(b"\x89PNG\r\n\x1a\n") or len(data) < 33:
        raise ValueError(f"invalid PNG file: {path}")
    if data[12:16] != b"IHDR":
        raise ValueError(f"PNG missing IHDR chunk: {path}")
    _, _, bit_depth, color_type = struct.unpack(">IIBB", data[16:26])
    chunk_types: set[bytes] = set()
    pos = 8
    n = len(data)
    while pos + 8 <= n:
        length = struct.unpack(">I", data[pos : pos + 4])[0]
        ctype = data[pos + 4 : pos + 8]
        chunk_types.add(ctype)
        pos += 12 + length
        if ctype == b"IEND":
            break
    return bit_depth, color_type, chunk_types


def load_managed_pass(path: Path) -> ManagedImage:
    """Load an aligned PNG or TIFF pass at true 8-bit or 16-bit depth."""
    path = Path(path)
    with Image.open(path) as image:
        fmt = image.format
        if fmt not in ("PNG", "TIFF"):
            raise ValueError(f"unsupported pass format {fmt!r} for {path.name}; supply PNG or TIFF")
        raw_orientation = image.getexif().get(274, 1)
        if not isinstance(raw_orientation, int) or raw_orientation not in VALID_ORIENTATIONS:
            raise ValueError(f"invalid EXIF orientation {raw_orientation!r} in {path.name}")
        icc = image.info.get("icc_profile")
        icc_desc = validate_icc_profile(icc) if icc is not None else "untagged_assumed_sRGB"

        if fmt == "PNG":
            bit_depth, color_type, chunk_types = _read_png_header(path)
            if color_type not in (2, 6):
                raise ValueError(
                    f"PNG color type {color_type} in {path.name} is unsupported; "
                    "only 8/16-bit RGB or RGBA PNG passes are accepted"
                )
            if bit_depth not in (8, 16):
                raise ValueError(f"unsupported PNG bit depth {bit_depth} in {path.name}")
            if b"tRNS" in chunk_types or "transparency" in image.info:
                raise ValueError(
                    f"PNG {path.name} uses colour-key transparency (tRNS); "
                    "convert to straight RGBA alpha before export"
                )
            if (
                icc is None
                and b"iCCP" not in chunk_types
                and b"sRGB" not in chunk_types
                and "srgb" not in image.info
                and (
                    b"gAMA" in chunk_types
                    or b"cHRM" in chunk_types
                    or "gamma" in image.info
                    or "chromaticity" in image.info
                )
            ):
                raise ValueError(
                    f"PNG {path.name} carries non-sRGB gAMA/cHRM colour tags without an ICC profile "
                    "or sRGB chunk; convert to sRGB or embed an explicit ICC profile"
                )
            has_alpha = color_type == 6
            if bit_depth == 8:
                expected_mode = "RGBA" if has_alpha else "RGB"
                if image.mode != expected_mode:
                    raise ValueError(f"unexpected PNG mode {image.mode!r} in {path.name}")
                arr = np.array(image, dtype=np.uint8)
            else:
                raw_bytes = path.read_bytes()
                dec = cv2.imdecode(np.frombuffer(raw_bytes, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
                if dec is None or dec.dtype != np.uint16 or dec.ndim != 3:
                    raise ValueError(f"failed to decode 16-bit PNG pixels from {path.name}")
                if has_alpha and dec.shape[2] == 4:
                    arr = cv2.cvtColor(dec, cv2.COLOR_BGRA2RGBA)
                elif not has_alpha and dec.shape[2] == 3:
                    arr = cv2.cvtColor(dec, cv2.COLOR_BGR2RGB)
                else:
                    raise ValueError(f"unexpected 16-bit PNG channel layout {dec.shape} in {path.name}")
            normalized = normalize_exif_orientation(arr, raw_orientation)
        else:
            photometric = image.tag_v2.get(262)
            if photometric != 2:
                raise ValueError(
                    f"TIFF PhotometricInterpretation={photometric!r} in {path.name} is unsupported; "
                    "only RGB/RGBA TIFFs are accepted"
                )
            bps = image.tag_v2.get(258, (8,))
            if isinstance(bps, int):
                bps = (bps,)
            if len(set(bps)) != 1 or bps[0] not in (8, 16):
                raise ValueError(f"unsupported TIFF BitsPerSample={bps!r} in {path.name}")
            bit_depth = int(bps[0])
            samples = int(image.tag_v2.get(277, len(bps)))
            if samples not in (3, 4):
                raise ValueError(f"unsupported TIFF SamplesPerPixel={samples} in {path.name}")
            has_alpha = samples == 4
            if has_alpha:
                extra = image.tag_v2.get(338, ())
                if isinstance(extra, int):
                    extra = (extra,)
                if extra == (1,):
                    raise ValueError(
                        f"TIFF {path.name} uses associated (premultiplied) alpha; "
                        "convert to straight unassociated alpha before export"
                    )
            if bit_depth == 8:
                expected_mode = "RGBA" if has_alpha else "RGB"
                if image.mode != expected_mode:
                    raise ValueError(f"unexpected 8-bit TIFF mode {image.mode!r} in {path.name}")
                # Pillow reads 8-bit TIFF straight alpha intact and applies IFD orientation (1..8).
                normalized = np.ascontiguousarray(np.array(image, dtype=np.uint8))
            else:
                raw_bytes = path.read_bytes()
                # OpenCV preserves 16-bit straight alpha and applies TIFF IFD orientation (1..8).
                dec = cv2.imdecode(np.frombuffer(raw_bytes, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
                if dec is None or dec.ndim != 3 or dec.shape[2] != samples:
                    raise ValueError(f"failed to decode 16-bit TIFF pixels from {path.name}")
                if dec.dtype != np.uint16:
                    raise ValueError(f"TIFF decoded dtype {dec.dtype} does not match BitsPerSample=16")
                if dec.shape[:2] != (image.height, image.width):
                    raise ValueError(
                        f"TIFF decoded shape {dec.shape[:2]} does not match normalized shape {(image.height, image.width)}"
                    )
                normalized = np.ascontiguousarray(
                    cv2.cvtColor(dec, cv2.COLOR_BGRA2RGBA if has_alpha else cv2.COLOR_BGR2RGB)
                )
    return ManagedImage(
        pixels=normalized,
        source_bit_depth=bit_depth,
        has_alpha=has_alpha,
        icc_profile=icc,
        icc_description=icc_desc,
        raw_orientation=raw_orientation,
        normalized_orientation=1,
        source_format=fmt,
    )


def _encode_png(pixels: np.ndarray, icc_profile: Optional[bytes]) -> bytes:
    h, w, c = pixels.shape
    bit_depth = 16 if pixels.dtype == np.uint16 else 8
    color_type = 6 if c == 4 else 2

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    out = bytearray(b"\x89PNG\r\n\x1a\n")
    out += chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, bit_depth, color_type, 0, 0, 0))
    if icc_profile:
        out += chunk(b"iCCP", b"ICC Profile\x00\x00" + zlib.compress(icc_profile))
    if bit_depth == 16:
        scan_body = pixels.astype(">u2", copy=False).reshape(h, w * c).view(np.uint8)
    else:
        scan_body = pixels.astype(np.uint8, copy=False).reshape(h, w * c)
    raw = np.empty((h, 1 + scan_body.shape[1]), dtype=np.uint8)
    raw[:, 0] = 0
    raw[:, 1:] = scan_body
    out += chunk(b"IDAT", zlib.compress(raw.tobytes()))
    out += chunk(b"IEND", b"")
    return bytes(out)


def _encode_tiff(pixels: np.ndarray, icc_profile: Optional[bytes]) -> bytes:
    h, w, c = pixels.shape
    bit_depth = 16 if pixels.dtype == np.uint16 else 8
    raw = pixels.astype("<u2" if bit_depth == 16 else np.uint8, copy=False).tobytes()
    bps_bytes = struct.pack(f"<{c}H", *([bit_depth] * c))

    n_tags = 11 + (1 if c == 4 else 0) + (1 if icc_profile else 0)
    ifd_offset = 8
    ifd_size = 2 + n_tags * 12 + 4
    bps_offset = ifd_offset + ifd_size
    extra = bytearray(bps_bytes)
    if icc_profile:
        icc_offset = bps_offset + len(extra)
        extra += icc_profile
    pixel_offset = bps_offset + len(extra)

    def entry(tag: int, typ: int, cnt: int, val: int) -> bytes:
        return struct.pack("<HHII", tag, typ, cnt, val)

    tags = [
        entry(256, 4, 1, w),
        entry(257, 4, 1, h),
        entry(258, 3, c, bps_offset),
        entry(259, 3, 1, 1),  # uncompressed lossless baseline
        entry(262, 3, 1, 2),  # RGB photometric
        entry(273, 4, 1, pixel_offset),
        entry(274, 3, 1, 1),  # EXIF orientation explicitly normalized to 1
        entry(277, 3, 1, c),
        entry(278, 4, 1, h),
        entry(279, 4, 1, len(raw)),
        entry(284, 3, 1, 1),  # chunky planar
    ]
    if c == 4:
        tags.append(entry(338, 3, 1, 2))  # unassociated / straight alpha
    if icc_profile:
        tags.append(entry(34675, 7, len(icc_profile), icc_offset))

    out = bytearray(b"II*\x00" + struct.pack("<I", ifd_offset))
    out += struct.pack("<H", len(tags))
    for tag in tags:
        out += tag
    out += struct.pack("<I", 0)
    out += extra
    out += raw
    return bytes(out)


def encode_managed_image(pixels: np.ndarray, *, icc_profile: Optional[bytes] = None, file_format: str = "png") -> bytes:
    """Encode RGB/RGBA uint8 or uint16 array cleanly into lossless PNG or TIFF bytes."""
    if pixels.ndim != 3 or pixels.shape[2] not in (3, 4) or min(pixels.shape[:2]) < 1:
        raise ValueError("exported image must have non-empty H x W x 3/4 shape")
    if pixels.dtype not in (np.uint8, np.uint16):
        raise ValueError("exported image dtype must be uint8 or uint16")
    if icc_profile is not None:
        validate_icc_profile(icc_profile)
    fmt = file_format.lower()
    if fmt == "png":
        return _encode_png(pixels, icc_profile)
    if fmt in ("tif", "tiff"):
        return _encode_tiff(pixels, icc_profile)
    raise ValueError(f"unsupported output format {file_format!r}; choose png or tiff")


def _scale_pixels_precision(pixels: np.ndarray, target_bit_depth: int) -> np.ndarray:
    cur_depth = 16 if pixels.dtype == np.uint16 else 8
    if cur_depth == target_bit_depth:
        return pixels.copy()
    if cur_depth == 8 and target_bit_depth == 16:
        # 255 * 257 == 65535 exact endpoint bijection without fake detail.
        return pixels.astype(np.uint16) * 257
    return np.clip(np.rint(pixels.astype(np.float64) / 257.0), 0, 255).astype(np.uint8)


def compose_managed_passes(
    base: ManagedImage,
    texture: ManagedImage,
    *,
    skin=None,
    hair=None,
    fabric=None,
    protected=None,
    confidence=None,
    edge_guard=None,
    interior_texture=None,
    blend: RegionBlend = RegionBlend(),
    icc_policy: str = "preserve",
    target_icc: Optional[bytes] = None,
    icc_intent: str = "relative_colorimetric",
    alpha_mode: str = "preserve_base",
    bit_depth: str | int = "auto",
    grain_strength: float = 0.0,
    grain_seed: int = 0,
    allow_8bit_lut: bool = False,
) -> tuple[ManagedImage, np.ndarray, dict]:
    """Compose aligned passes with colour management, straight alpha and precision control."""
    if base.pixels.shape[:2] != texture.pixels.shape[:2]:
        raise ValueError(
            "normalized passes must have identical dimensions; no implicit resizing"
        )
    if icc_policy not in ICC_POLICIES:
        raise ValueError(f"unsupported icc_policy {icc_policy!r}; expected {sorted(ICC_POLICIES)}")
    if icc_intent not in INTENTS:
        raise ValueError(f"unsupported icc_intent {icc_intent!r}; expected {sorted(INTENTS)}")
    if alpha_mode not in ALPHA_MODES:
        raise ValueError(f"unsupported alpha_mode {alpha_mode!r}; expected {sorted(ALPHA_MODES)}")
    if not math.isfinite(grain_strength) or not 0.0 <= grain_strength <= 0.25:
        raise ValueError("grain_strength must be finite and in [0.0, 0.25]")
    if texture.has_alpha and not base.has_alpha:
        raise ValueError("texture carries an alpha channel while base does not")

    if bit_depth == "auto":
        out_bits = max(base.source_bit_depth, texture.source_bit_depth)
    elif bit_depth in (8, 16, "8", "16"):
        out_bits = int(bit_depth)
    else:
        raise ValueError(f"unsupported bit_depth {bit_depth!r}; choose 'auto', 8 or 16")

    if icc_policy == "custom":
        if target_icc is None:
            raise ValueError("icc_policy='custom' requires target_icc bytes")
        target_desc = validate_icc_profile(target_icc)
        output_icc: Optional[bytes] = target_icc
    elif icc_policy == "srgb":
        output_icc = srgb_icc_bytes()
        target_desc = validate_icc_profile(output_icc)
    else:
        # 'preserve': keep base's profile (or untagged sRGB if neither tagged;
        # if only texture was tagged, convert texture to canonical sRGB).
        output_icc = base.icc_profile
        target_desc = base.icc_description

    # Bring both passes cleanly to identical target bit precision before/with ICC transform.
    working_bits = max(base.source_bit_depth, texture.source_bit_depth, out_bits)
    base_work = _scale_pixels_precision(base.pixels, working_bits)
    tex_work = _scale_pixels_precision(texture.pixels, working_bits)

    dst_profile_for_transform = srgb_icc_bytes() if output_icc is None else output_icc
    base_icc_path = "identity"
    tex_icc_path = "identity"

    if icc_policy != "preserve" or (base.icc_profile is not None and output_icc is None):
        if base.icc_profile != output_icc:
            base_work, base_icc_path = convert_icc_pixels(
                base_work,
                base.icc_profile,
                dst_profile_for_transform,
                intent=icc_intent,
                allow_8bit_lut=allow_8bit_lut,
            )
    if (texture.icc_profile or srgb_icc_bytes()) != dst_profile_for_transform:
        tex_work, tex_icc_path = convert_icc_pixels(
            tex_work,
            texture.icc_profile,
            dst_profile_for_transform,
            intent=icc_intent,
            allow_8bit_lut=allow_8bit_lut,
        )

    shape = base.pixels.shape[:2]
    skin_m = _mask(skin, shape, "skin")
    hair_m = _mask(hair, shape, "hair")
    fabric_m = _mask(fabric, shape, "fabric")
    protected_m = _mask(protected, shape, "protected")
    confidence_m = _mask(confidence, shape, "confidence")
    edge_m = _mask(edge_guard, shape, "edge_guard")
    if interior_texture is not None:
        interior_texture_m = _mask(interior_texture, shape, "interior_texture")
        effective_edge_m = edge_m * (1.0 - interior_texture_m)
    else:
        effective_edge_m = edge_m

    total = np.maximum(1.0, skin_m + hair_m + fabric_m)
    eff_alpha = (skin_m * blend.skin + hair_m * blend.hair + fabric_m * blend.fabric) / total
    eff_alpha *= confidence_m * (1.0 - protected_m)
    eff_alpha *= 1.0 - effective_edge_m * blend.edge_protection
    eff_alpha = np.clip(eff_alpha, 0.0, 1.0).astype(np.float64)

    max_work = float((1 << working_bits) - 1)
    if base.has_alpha:
        base_alpha_f = base_work[..., 3].astype(np.float64) / max_work
        # Keep transparent background and mask-blended edges straight-alpha safe.
        eff_alpha *= base_alpha_f
    else:
        base_alpha_f = None
    if texture.has_alpha:
        eff_alpha *= tex_work[..., 3].astype(np.float64) / max_work

    working_mt = parse_matrix_trc_icc(dst_profile_for_transform)
    lut_working_fallback = False
    if working_mt is None:
        if not allow_8bit_lut:
            raise ValueError(
                "linear-light blending requires a Matrix/TRC working ICC profile "
                "or allow_8bit_lut=True fallback"
            )
        lut_working_fallback = True
        srgb_profile = srgb_icc_bytes()
        working_mt = parse_matrix_trc_icc(srgb_profile)
        assert working_mt is not None
        base_blend_work, base_icc_path = convert_icc_pixels(
            _scale_pixels_precision(base.pixels, working_bits),
            base.icc_profile,
            srgb_profile,
            intent=icc_intent,
            allow_8bit_lut=True,
        )
        tex_blend_work, tex_icc_path = convert_icc_pixels(
            _scale_pixels_precision(texture.pixels, working_bits),
            texture.icc_profile,
            srgb_profile,
            intent=icc_intent,
            allow_8bit_lut=True,
        )
    else:
        base_blend_work = base_work
        tex_blend_work = tex_work

    base_rgb01 = base_blend_work[..., :3].astype(np.float64) / max_work
    tex_rgb01 = tex_blend_work[..., :3].astype(np.float64) / max_work
    lin_base = _linearize_rgb(base_rgb01, working_mt)
    lin_tex = _linearize_rgb(tex_rgb01, working_mt)
    lin_blend = lin_base * (1.0 - eff_alpha[..., None]) + lin_tex * eff_alpha[..., None]
    enc_out = _encode_rgb(lin_blend, working_mt)

    if grain_strength > 0.0:
        rng = np.random.default_rng(int(grain_seed))
        luma_noise = rng.normal(0.0, float(grain_strength), size=(shape[0], shape[1], 1))
        enc_out = np.clip(enc_out + luma_noise * eff_alpha[..., None], 0.0, 1.0)

    out_max = float((1 << out_bits) - 1)
    out_dtype = np.uint16 if out_bits == 16 else np.uint8
    out_rgb = np.clip(np.rint(enc_out * out_max), 0, out_max).astype(out_dtype)
    if lut_working_fallback:
        out_rgb, _ = convert_icc_pixels(
            out_rgb,
            srgb_icc_bytes(),
            dst_profile_for_transform,
            intent=icc_intent,
            allow_8bit_lut=True,
        )

    # Restore locked / unchanged pixels strictly last after quantization & finishing.
    base_target_out = _scale_pixels_precision(base_work[..., :3], out_bits)
    locked = (protected_m == 1.0) | (eff_alpha == 0.0)
    if base_alpha_f is not None:
        locked = locked | (base_work[..., 3] == 0)
    out_rgb[locked] = base_target_out[locked]

    keep_alpha = base.has_alpha and alpha_mode == "preserve_base"
    if keep_alpha:
        alpha_out = _scale_pixels_precision(base_work[..., 3:4], out_bits)
        out_pixels = np.concatenate([out_rgb, alpha_out], axis=2)
    else:
        out_pixels = out_rgb

    source_max_bits = max(base.source_bit_depth, texture.source_bit_depth)
    container_promoted = out_bits > source_max_bits
    if container_promoted:
        precision_note = (
            f"{source_max_bits}-bit source wrapped in a {out_bits}-bit container after "
            "float64 linear blending; does not represent newly recovered source bit depth."
        )
    else:
        precision_note = f"Exported at native {out_bits}-bit working/source precision."

    managed_out = ManagedImage(
        pixels=out_pixels,
        source_bit_depth=out_bits,
        has_alpha=keep_alpha,
        icc_profile=output_icc,
        icc_description=target_desc,
        raw_orientation=1,
        normalized_orientation=1,
        source_format="ARRAY",
    )

    metadata = {
        "schema_version": 1,
        "operation": "managed_region_export",
        "inference_executed": False,
        "working_precision": "float64-linear",
        "source_bit_depth": {"base": base.source_bit_depth, "texture": texture.source_bit_depth},
        "output_bit_depth": out_bits,
        "container_precision_exceeds_source": bool(container_promoted),
        "newly_recovered_source_detail": False,
        "precision_note": precision_note,
        "orientation_normalized": {
            "base": base.raw_orientation,
            "texture": texture.raw_orientation,
            "output": 1,
        },
        "has_alpha": bool(keep_alpha),
        "alpha_mode": alpha_mode,
        "alpha_semantics": "straight" if keep_alpha else "none",
        "icc_policy": icc_policy,
        "icc_intent": icc_intent,
        "icc_description": target_desc,
        "source_icc_sha256": {
            "base": _sha256_bytes(base.icc_profile) if base.icc_profile else None,
            "texture": _sha256_bytes(texture.icc_profile) if texture.icc_profile else None,
        },
        "output_icc_sha256": _sha256_bytes(output_icc) if output_icc else None,
        "icc_precision_path": {"base": base_icc_path, "texture": tex_icc_path},
        "grain_strength": float(grain_strength),
        "grain_enabled": bool(grain_strength > 0.0),
        "locked_pixel_fraction": float(locked.mean()),
        "alpha_mean": float(eff_alpha.mean()),
        "alpha_max": float(eff_alpha.max()),
        "dimensions": [int(out_pixels.shape[1]), int(out_pixels.shape[0])],
        "blend": asdict(blend),
    }
    return managed_out, eff_alpha.astype(np.float32), metadata


def export_verified_master(
    output_path: Path,
    image: ManagedImage,
    metadata: dict,
    *,
    input_paths: dict[str, Path],
    profile: str,
) -> tuple[Path, Path, dict]:
    """Atomically write output image + recipe JSON after full encode/decode check."""
    output_path = Path(output_path)
    ext = output_path.suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"unsupported output extension {ext!r}; use .png, .tif, or .tiff")
    fmt = SUPPORTED_EXTENSIONS[ext]
    sidecar = Path(f"{output_path}.recipe.json")

    resolved_inputs = {p.resolve() for p in input_paths.values()}
    if output_path.resolve() in resolved_inputs or sidecar.resolve() in resolved_inputs:
        raise ValueError("output and sidecar paths must not overwrite an input")

    encoded = encode_managed_image(image.pixels, icc_profile=image.icc_profile, file_format=fmt)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output_path.parent, prefix=".export-") as temp:
        tmp_img = Path(temp) / f"master{ext}"
        tmp_img.write_bytes(encoded)
        decoded = load_managed_pass(tmp_img)
        if not np.array_equal(decoded.pixels, image.pixels):
            raise ValueError("encoded output failed bit-exact pixel verification")
        if decoded.source_bit_depth != image.source_bit_depth:
            raise ValueError("encoded output bit depth did not match requested precision")
        if decoded.has_alpha != image.has_alpha:
            raise ValueError("encoded output alpha channel did not match expectation")
        if decoded.normalized_orientation != 1 or decoded.raw_orientation != 1:
            raise ValueError("encoded output failed orientation=1 normalization check")
        if decoded.icc_profile != image.icc_profile:
            raise ValueError("encoded output ICC profile bytes differed after round-trip")

        record = {
            **metadata,
            "profile": profile,
            "output_format": fmt.upper(),
            "verified_roundtrip": True,
            "inputs": {name: sha256_file(path) for name, path in input_paths.items()},
            "output_sha256": sha256_file(tmp_img),
            "provenance": "unsigned_execution_record",
        }
        tmp_sidecar = Path(temp) / "recipe.json"
        tmp_sidecar.write_text(json_dumps(record), encoding="utf-8")
        os.replace(tmp_img, output_path)
        os.replace(tmp_sidecar, sidecar)
    return output_path, sidecar, record


def json_dumps(payload: dict) -> str:
    import json

    return json.dumps(payload, indent=2) + "\n"
