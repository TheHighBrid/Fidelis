"""Validate the PNG encoding before Pillow converts pixel samples."""
import hashlib
import io
import struct
import zlib
from pathlib import Path

import numpy as np
from PIL import Image


class PngPixelLimit(ValueError):
    pass


_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_IEND_CRC = zlib.crc32(b"IEND") & 0xFFFFFFFF


def _png_encoding(stream):
    header = stream.read(26)
    stream.seek(0)
    if len(header) != 26 or header[:16] != b"\x89PNG\r\n\x1a\n\x00\x00\x00\x0dIHDR":
        raise ValueError("Supply a PNG with a valid image header")
    return header[24], header[25]


def _check_geometry(image, max_pixels, expected_size=None):
    # APNG decoders expose frame zero as a normal RGB image. A single-pass
    # contract must not silently discard later frames or timing metadata.
    if getattr(image, "n_frames", 1) != 1 or getattr(image, "is_animated", False):
        raise ValueError("Animated or multi-frame PNG passes are not supported")
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


def _validate_expected_size(expected_size):
    if (
        not isinstance(expected_size, (tuple, list))
        or len(expected_size) != 2
        or any(isinstance(v, bool) or not isinstance(v, int) or v < 1 for v in expected_size)
    ):
        raise ValueError(f"expected_size must be a positive (width, height) pair, got {expected_size!r}")
    return int(expected_size[0]), int(expected_size[1])


def _validate_expected_mode(expected_mode):
    if expected_mode == "RGB":
        return 2, 3
    if expected_mode == "RGBA":
        return 6, 4
    raise ValueError(f"Unsupported cached PNG expected_mode {expected_mode!r}; expected 'RGB' or 'RGBA'")


def _read_exact(stream, size, message):
    data = stream.read(size)
    if len(data) != size:
        raise ValueError(message)
    return data


def _scan_chunk_crc(stream, chunk_type, length, *, verify_crc):
    crc = zlib.crc32(chunk_type)
    remaining = length
    if verify_crc:
        while remaining > 0:
            block = _read_exact(stream, min(remaining, 1024 * 1024), "Truncated PNG chunk payload")
            crc = zlib.crc32(block, crc)
            remaining -= len(block)
    elif length > 0:
        stream.seek(length, 1)
    expected_crc = struct.unpack(">I", _read_exact(stream, 4, "Truncated PNG chunk CRC"))[0]
    if verify_crc and (crc & 0xFFFFFFFF) != expected_crc:
        raise ValueError(f"PNG {chunk_type.decode('ascii', 'replace')} chunk CRC mismatch")


def inspect_cached_generated_png(
    path,
    *,
    expected_size,
    expected_mode="RGB",
    max_pixels=None,
    verify_crc=False,
):
    """Validate format, mode, native dimensions, and IEND integrity of a cached PNG.

    Never alters Pillow's global `Image.MAX_IMAGE_PIXELS` or weakens public upload limits.
    """
    exp_w, exp_h = _validate_expected_size(expected_size)
    expected_color_type, channels = _validate_expected_mode(expected_mode)
    if max_pixels is not None and (isinstance(max_pixels, bool) or not isinstance(max_pixels, int) or max_pixels < 1):
        raise ValueError(f"max_pixels must be a positive integer or None, got {max_pixels!r}")

    src_path = Path(path)
    if not src_path.is_file():
        raise FileNotFoundError(f"Cached PNG file not found: {src_path}")

    file_hash = hashlib.sha256()
    with src_path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            file_hash.update(block)
        stream.seek(0)

        sig = _read_exact(stream, 8, "Supply a PNG with a valid image header")
        if sig != _PNG_SIGNATURE:
            raise ValueError("Supply a PNG with a valid image header")

        first_len, first_type = struct.unpack(">I4s", _read_exact(stream, 8, "Missing PNG IHDR header"))
        if first_type != b"IHDR" or first_len != 13:
            raise ValueError("Supply a PNG with a valid IHDR header")
        ihdr_bytes = _read_exact(stream, 13, "Truncated PNG IHDR chunk")
        ihdr_crc = struct.unpack(">I", _read_exact(stream, 4, "Truncated PNG IHDR CRC"))[0]
        if (zlib.crc32(b"IHDR" + ihdr_bytes) & 0xFFFFFFFF) != ihdr_crc:
            raise ValueError("PNG IHDR chunk CRC mismatch")

        width, height, bit_depth, color_type, compression, filter_method, interlace = struct.unpack(
            ">IIBBBBB", ihdr_bytes
        )
        if compression != 0 or filter_method != 0 or interlace not in (0, 1):
            raise ValueError("Unsupported PNG compression, filter, or interlace header")
        if bit_depth != 8 or color_type != expected_color_type:
            raise ValueError(
                f"Cached PNG mode/depth mismatch: expected 8-bit {expected_mode}, "
                f"got bit_depth={bit_depth}, color_type={color_type}"
            )
        if (width, height) != (exp_w, exp_h):
            raise ValueError(
                f"Cached PNG dimensions {width}x{height} do not match expected native size {exp_w}x{exp_h}; "
                "silent resizing is forbidden"
            )
        if max_pixels is not None and width * height > max_pixels:
            raise PngPixelLimit("Cached PNG exceeds configured pixel limit")

        has_srgb = False
        has_non_srgb_tag = False
        has_idat = False
        saw_iend = False

        while True:
            hdr = stream.read(8)
            if not hdr:
                break
            if len(hdr) != 8:
                raise ValueError("Truncated PNG chunk header")
            length, chunk_type = struct.unpack(">I4s", hdr)
            if chunk_type == b"acTL":
                raise ValueError("Animated or multi-frame PNG passes are not supported")
            if chunk_type == b"tRNS":
                raise ValueError("Normalize orientation and use explicit alpha samples")
            if chunk_type == b"iCCP":
                raise ValueError("Cached PNG carries an ICC profile; untagged sRGB is required")
            if chunk_type == b"sRGB":
                has_srgb = True
            elif chunk_type in (b"gAMA", b"cHRM"):
                has_non_srgb_tag = True
            elif chunk_type == b"IDAT":
                has_idat = True

            if chunk_type == b"IEND":
                if length != 0:
                    raise ValueError("PNG IEND chunk must be empty")
                iend_crc = struct.unpack(">I", _read_exact(stream, 4, "Truncated PNG IEND CRC"))[0]
                if iend_crc != _IEND_CRC:
                    raise ValueError("PNG IEND chunk CRC mismatch")
                if stream.read(1):
                    raise ValueError("Trailing bytes found after PNG IEND chunk")
                saw_iend = True
                break

            _scan_chunk_crc(stream, chunk_type, length, verify_crc=verify_crc)

        if not has_idat or not saw_iend:
            raise ValueError("Cached PNG is incomplete or missing IEND")
        if has_non_srgb_tag and not has_srgb:
            raise ValueError("Convert tagged colour to sRGB before importing")

    return {
        "path": str(src_path),
        "format": "PNG",
        "mode": expected_mode,
        "bit_depth": 8,
        "channels": channels,
        "dimensions": [width, height],
        "interlace": interlace,
        "iend_complete": True,
        "file_bytes": src_path.stat().st_size,
        "sha256": file_hash.hexdigest(),
    }


def _consume_scanlines(buf, out, prev, row_idx, width, height, channels, stride):
    row_bytes = width * channels
    pos = 0
    while row_idx < height and len(buf) - pos >= stride:
        ftype = buf[pos]
        raw_row = np.frombuffer(buf, dtype=np.uint8, count=row_bytes, offset=pos + 1)
        recon = _unfilter_scanline(ftype, raw_row, prev, channels)
        out[row_idx] = recon.reshape(width, channels)
        prev = recon
        row_idx += 1
        pos += stride
    if pos:
        del raw_row
        del buf[:pos]
    return prev, row_idx


def _decode_png_scanlines_pure(path, width, height, channels):
    decompressor = zlib.decompressobj()
    buf = bytearray()
    stride = 1 + width * channels
    out = np.empty((height, width, channels), dtype=np.uint8)
    prev = np.zeros(width * channels, dtype=np.uint8)
    row_idx = 0

    with Path(path).open("rb") as stream:
        stream.seek(8)
        while True:
            hdr = stream.read(8)
            if len(hdr) != 8:
                break
            length, chunk_type = struct.unpack(">I4s", hdr)
            if chunk_type == b"IDAT":
                remaining = length
                while remaining > 0:
                    chunk = _read_exact(stream, min(remaining, 1024 * 1024), "Truncated PNG IDAT")
                    remaining -= len(chunk)
                    buf.extend(decompressor.decompress(chunk))
                    prev, row_idx = _consume_scanlines(
                        buf, out, prev, row_idx, width, height, channels, stride
                    )
                _read_exact(stream, 4, "Truncated PNG IDAT CRC")
            elif chunk_type == b"IEND":
                break
            else:
                stream.seek(length + 4, 1)
    buf.extend(decompressor.flush())
    prev, row_idx = _consume_scanlines(
        buf, out, prev, row_idx, width, height, channels, stride
    )
    if row_idx != height or not decompressor.eof or len(buf) != 0:
        raise ValueError("Cached PNG IDAT stream did not match expected scanlines")
    return out


def _unfilter_scanline(ftype, raw_row, prev, channels):
    if ftype == 0:
        return raw_row.copy()
    if ftype == 1:
        recon = raw_row.astype(np.uint16)
        for i in range(channels, len(recon)):
            recon[i] = (recon[i] + recon[i - channels]) & 0xFF
        return recon.astype(np.uint8)
    if ftype == 2:
        return ((raw_row.astype(np.uint16) + prev.astype(np.uint16)) & 0xFF).astype(np.uint8)
    if ftype == 3:
        recon = raw_row.astype(np.int32)
        prev_i = prev.astype(np.int32)
        for i in range(len(recon)):
            left = int(recon[i - channels]) if i >= channels else 0
            recon[i] = (recon[i] + ((left + int(prev_i[i])) >> 1)) & 0xFF
        return recon.astype(np.uint8)
    if ftype == 4:
        recon = raw_row.astype(np.int32)
        prev_i = prev.astype(np.int32)
        for i in range(len(recon)):
            a = int(recon[i - channels]) if i >= channels else 0
            b = int(prev_i[i])
            c = int(prev_i[i - channels]) if i >= channels else 0
            p = a + b - c
            pa = abs(p - a)
            pb = abs(p - b)
            pc = abs(p - c)
            pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
            recon[i] = (recon[i] + pr) & 0xFF
        return recon.astype(np.uint8)
    raise ValueError(f"Unsupported PNG filter type {ftype}")


def read_cached_generated_png(
    path,
    *,
    expected_size,
    expected_mode="RGB",
    max_pixels=None,
    verify_crc=False,
):
    """Validate and decode a cached generated PNG on its expected native grid.

    Decodes without globally modifying `Image.MAX_IMAGE_PIXELS` so public
    upload and import limits stay intact.
    """
    meta = inspect_cached_generated_png(
        path,
        expected_size=expected_size,
        expected_mode=expected_mode,
        max_pixels=max_pixels,
        verify_crc=verify_crc,
    )
    exp_w, exp_h = meta["dimensions"]
    channels = meta["channels"]
    src_path = Path(path)

    try:
        import cv2
    except ModuleNotFoundError:
        cv2 = None

    if cv2 is not None:
        raw = cv2.imread(str(src_path), cv2.IMREAD_UNCHANGED)
        if raw is None or raw.dtype != np.uint8 or raw.ndim != 3 or raw.shape != (exp_h, exp_w, channels):
            raise ValueError(
                f"Decoded cached PNG shape/dtype mismatch: expected {(exp_h, exp_w, channels)} uint8"
            )
        if channels == 3:
            return cv2.cvtColor(raw, cv2.COLOR_BGR2RGB), meta
        return cv2.cvtColor(raw, cv2.COLOR_BGRA2RGBA), meta

    if meta["interlace"] != 0:
        raise ValueError("Interlaced cached PNG decoding requires opencv-python")
    return _decode_png_scanlines_pure(src_path, exp_w, exp_h, channels), meta
