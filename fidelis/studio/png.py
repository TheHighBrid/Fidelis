"""Validate the PNG encoding before Pillow converts pixel samples."""
import io
import struct
import zlib

import numpy as np
from PIL import Image


class PngPixelLimit(ValueError):
    pass


def _png_encoding(stream):
    header = stream.read(26)
    stream.seek(0)
    if len(header) != 26 or header[:16] != b"\x89PNG\r\n\x1a\n\x00\x00\x00\x0dIHDR":
        raise ValueError("Supply a PNG with a valid image header")
    return header[24], header[25]


def _check_geometry(image, max_pixels, expected_size=None):
    if image.width * image.height > max_pixels:
        raise PngPixelLimit("Image exceeds configured pixel limit")
    if expected_size is not None and image.size != expected_size:
        raise ValueError("Image changed dimensions; no implicit resize is allowed")
    if "transparency" in image.info or image.getexif().get(274, 1) != 1:
        raise ValueError("Normalize orientation and use explicit alpha samples")


def _check_colour(image):
    if "srgb" not in image.info and ("gamma" in image.info or "chromaticity" in image.info):
        raise ValueError("Convert tagged colour to sRGB before importing")


def read_rgb8_png(stream, *, max_pixels=40_000_000, expected_size=None):
    """Read an aligned sRGB pass without implicit bit-depth or alpha conversion."""
    if _png_encoding(stream) != (8, 2):
        raise ValueError("Supply 8-bit RGB PNGs in sRGB working space")
    with Image.open(stream) as image:
        _check_geometry(image, max_pixels, expected_size)
        if image.mode != "RGB" or image.info.get("icc_profile"):
            raise ValueError("Normalize colour and remove transparency before importing")
        _check_colour(image)
        return np.array(image)


def write_rgb_png(array, stream, *, max_bytes=None):
    """Encode RGB or straight-alpha RGBA scanlines without building a full-frame Pillow copy."""
    if (array.ndim != 3 or array.shape[2] not in (3, 4) or min(array.shape[:2]) < 1
            or array.dtype not in (np.uint8, np.uint16)):
        raise ValueError("PNG image must have RGB or RGBA uint8/uint16 samples")
    depth = array.dtype.itemsize * 8
    color_type = 2 if array.shape[2] == 3 else 6
    written = 8
    if max_bytes is not None and written > max_bytes:
        raise ValueError("PNG export exceeds the byte budget")

    def chunk(kind, data):
        nonlocal written
        written += 12 + len(data)
        if max_bytes is not None and written > max_bytes:
            raise ValueError("PNG export exceeds the byte budget")
        stream.write(struct.pack(">I", len(data)))
        stream.write(kind)
        stream.write(data)
        stream.write(struct.pack(">I", zlib.crc32(data, zlib.crc32(kind)) & 0xffffffff))
    stream.write(b"\x89PNG\r\n\x1a\n")
    chunk(b"IHDR", struct.pack(">IIBBBBB", array.shape[1], array.shape[0], depth, color_type, 0, 0, 0))
    chunk(b"sRGB", b"\x00")
    compressor = zlib.compressobj(6)
    for row in array:
        if depth == 16:
            row = row.astype(">u2", copy=False)
        encoded = compressor.compress(b"\x00" + row.tobytes())
        if encoded:
            chunk(b"IDAT", encoded)
    chunk(b"IDAT", compressor.flush())
    chunk(b"IEND", b"")


def read_export_pass(path, *, allow_alpha=False, convert_icc=False):
    """Read a CLI export pass while retaining its encoded sample depth."""
    from PIL import ImageCms

    with path.open("rb") as stream:
        depth, color_type = _png_encoding(stream)
        color_types = (2, 6) if allow_alpha else (2,)
        if depth not in (8, 16) or color_type not in color_types:
            raise ValueError("Supply RGB PNG passes, with optional straight alpha on the base")
        with Image.open(stream) as image:
            _check_geometry(image, 40_000_000)
            icc = image.info.get("icc_profile")
            if not icc:
                _check_colour(image)
            if icc:
                if not convert_icc or depth != 8:
                    raise ValueError("Convert profiled passes to sRGB, or opt into RGB8 ICC conversion")
                alpha = image.getchannel("A") if image.mode == "RGBA" else None
                try:
                    rgb = ImageCms.profileToProfile(image.convert("RGB"), io.BytesIO(icc),
                                                    ImageCms.createProfile("sRGB"), outputMode="RGB")
                except ImageCms.PyCMSError as error:
                    raise ValueError("Invalid or unsupported RGB ICC profile") from error
                if alpha is not None:
                    rgb.putalpha(alpha)
                return np.array(rgb), True
            if depth == 8:
                return np.array(image), False
        stream.seek(0)
        import cv2

        raw = cv2.imdecode(np.frombuffer(stream.read(), np.uint8), cv2.IMREAD_UNCHANGED)
        channels = 4 if color_type == 6 else 3
        if raw is None or raw.dtype != np.uint16 or raw.ndim != 3 or raw.shape[2] != channels:
            raise ValueError("Could not retain encoded 16-bit PNG samples")
        return raw[:, :, [2, 1, 0, 3] if channels == 4 else [2, 1, 0]], False
