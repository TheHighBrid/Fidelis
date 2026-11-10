"""Local-only HTTP bridge for persistent regional reblending."""
import base64
from dataclasses import asdict
import io
import ipaddress
import json
import math
from pathlib import Path
import zipfile
from urllib.parse import parse_qs, urlparse

import numpy as np
from PIL import Image

from fidelis.postprocess.regions import PROFILES, RegionBlend
from fidelis.studio.store import MASK_NAMES, BudgetExceeded, JobStore, RevisionConflict, write_rgb_png

MAX_BODY = 48 * 1024**2
MAX_PREVIEW_PIXELS = 1_000_000


def _json(handler, status, payload):
    body = json.dumps(payload, allow_nan=False).encode()
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.end_headers()
    handler.wfile.write(body)


def _local_request(handler):
    if not ipaddress.ip_address(handler.client_address[0]).is_loopback:
        raise PermissionError("Regional workspace accepts loopback clients only")
    host = handler.headers.get("Host", "")
    parsed = urlparse("http://" + host)
    if parsed.hostname not in ("localhost", "127.0.0.1", "::1"):
        raise PermissionError("Regional workspace is available through localhost only")
    origin = handler.headers.get("Origin")
    if origin is not None and origin != "http://" + host:
        raise PermissionError("Cross-origin workspace access is not allowed")


def _bytes(value):
    if not isinstance(value, str):
        raise ValueError("Expected a base64 encoded file")
    return base64.b64decode(value.split(",", 1)[-1], validate=True)


def _image(value, max_pixels):
    with Image.open(io.BytesIO(_bytes(value))) as image:
        if image.width * image.height > max_pixels:
            raise BudgetExceeded("Image exceeds configured pixel limit")
        if image.format != "PNG" or image.mode != "RGB" or image.info.get("icc_profile"):
            raise ValueError("Supply untagged 8-bit RGB PNGs converted to sRGB")
        if image.getexif().get(274, 1) != 1:
            raise ValueError("Normalize image orientation before importing")
        return np.array(image)


def _masks(value, shape):
    raw = _bytes(value)
    # Inspect decompressed size before NumPy allocates arrays, including zip bombs.
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        names = archive.namelist()
        if len(names) > 6 or len(names) != len(set(names)):
            raise ValueError("Mask archive contains duplicate or excessive entries")
        if sum(item.file_size for item in archive.infolist()) > math.prod(shape) * 6 * 8 + 8192:
            raise BudgetExceeded("Decoded mask archive exceeds the image mask budget")
        for item in archive.infolist():
            if item.filename not in {name + ".npy" for name in MASK_NAMES}:
                raise ValueError("Unsupported mask archive entry")
            with archive.open(item) as stream:
                version = np.lib.format.read_magic(stream)
                if version == (1, 0):
                    dimensions, fortran, dtype = np.lib.format.read_array_header_1_0(stream)
                elif version == (2, 0):
                    dimensions, fortran, dtype = np.lib.format.read_array_header_2_0(stream)
                else:
                    raise ValueError("Unsupported mask array format")
                if dimensions != tuple(shape) or dtype.kind not in "uif" or dtype.itemsize > 8:
                    raise ValueError("Mask array contract does not match the image")
                if math.prod(dimensions) * dtype.itemsize > item.file_size:
                    raise ValueError("Truncated mask array")
    with np.load(io.BytesIO(raw), allow_pickle=False) as data:
        if "confidence" not in data.files:
            raise ValueError("Mask archive must contain explicit confidence")
        result = {name: data[name] for name in data.files}
    JobStore._validate_masks(result, shape)
    return result


def _public(manifest):
    return {key: value for key, value in manifest.items() if key != "artifacts"}


def dispatch(handler, workspace_root):
    """Handle /regions and /api/regions/*; return False for unrelated requests."""
    url = urlparse(handler.path)
    if url.path != "/regions" and not url.path.startswith("/api/regions/"):
        return False
    try:
        _local_request(handler)
        if url.path in ("/regions", "/api/regions/editor.js") and handler.command == "GET":
            is_script = url.path.endswith(".js")
            content = (Path(__file__).with_name("editor.js" if is_script else "studio.html")).read_bytes()
            handler.send_response(200)
            handler.send_header("Content-Type", "text/javascript; charset=utf-8" if is_script else "text/html; charset=utf-8")
            handler.send_header("Content-Length", str(len(content)))
            handler.send_header("Cache-Control", "no-store")
            handler.end_headers()
            handler.wfile.write(content)
            return True
        if not hasattr(handler.server, "region_store"):
            handler.server.region_store = JobStore(
                getattr(handler.server, "region_workspace_root", workspace_root),
                **getattr(handler.server, "region_store_options", {}))
        store = handler.server.region_store
        parts = url.path.strip("/").split("/")
        if handler.command == "GET":
            if parts == ["api", "regions", "jobs"]:
                _json(handler, 200, {"jobs": [_public(job) for job in store.list()],
                                      "generation_enabled": getattr(handler.server, "generation_queue", None) is not None,
                                      "profiles": {name: asdict(blend) for name, blend in PROFILES.items()}})
            elif len(parts) in (5, 6) and parts[:3] == ["api", "regions", "jobs"] and parts[4] == "generations":
                queue = getattr(handler.server, "generation_queue", None)
                if queue is None:
                    _json(handler, 503, {"error": "Generation is not configured; select a trusted workflow at server startup"})
                else:
                    _json(handler, 200, {"tasks": queue.list(parts[3])} if len(parts) == 5 else queue.get(parts[3], parts[5]))
            elif len(parts) == 4 and parts[:3] == ["api", "regions", "jobs"]:
                _json(handler, 200, _public(store.get(parts[3])))
            elif len(parts) == 5 and parts[:3] == ["api", "regions", "jobs"] and parts[4] == "mask-data":
                query = parse_qs(url.query)
                _json(handler, 200, store.mask_data(parts[3], int(query.get("revision", ["0"])[0])))
            elif len(parts) == 5 and parts[:3] == ["api", "regions", "jobs"] and parts[4] == "mask-preview":
                query = parse_qs(url.query)
                array = store.mask_preview(parts[3], int(query.get("revision", ["0"])[0]))
                encoded = io.BytesIO()
                Image.fromarray(array).save(encoded, format="PNG")
                handler.send_response(200)
                handler.send_header("Content-Type", "image/png")
                handler.send_header("Cache-Control", "no-store")
                handler.send_header("Content-Length", str(encoded.tell()))
                handler.end_headers()
                handler.wfile.write(encoded.getvalue())
            elif len(parts) == 5 and parts[:3] == ["api", "regions", "jobs"] and parts[4] in ("preview", "export"):
                query = parse_qs(url.query)
                role = query.get("role", ["master"])[0]
                if role not in ("base", "texture", "master"):
                    raise ValueError("Unsupported image role")
                # Successful validation and decode occur before sending status 200.
                with store.open_array(parts[3], role, expected_revision=(
                        int(query["revision"][0]) if "revision" in query else None)) as array:
                    handler.send_response(200)
                    handler.send_header("Content-Type", "image/png")
                    handler.send_header("Cache-Control", "no-store")
                    handler.send_header("X-Content-Type-Options", "nosniff")
                    if parts[4] == "export":
                        handler.send_header("Content-Disposition", 'attachment; filename="fidelis_master.png"')
                        handler.end_headers()
                        write_rgb_png(array, handler.wfile)
                    else:
                        # Slice before Pillow to avoid a full-resolution RGB copy.
                        stride = max(1, math.ceil(math.sqrt(array.shape[0] * array.shape[1] / MAX_PREVIEW_PIXELS)))
                        preview = Image.fromarray(np.ascontiguousarray(array[::stride, ::stride]))
                        encoded = io.BytesIO()
                        preview.save(encoded, format="PNG")
                        handler.send_header("Content-Length", str(encoded.tell()))
                        handler.end_headers()
                        handler.wfile.write(encoded.getvalue())
            else:
                _json(handler, 404, {"error": "Unknown workspace endpoint"})
        elif handler.command == "POST":
            if handler.headers.get("Content-Type", "").split(";", 1)[0] != "application/json":
                raise ValueError("Content-Type must be application/json")
            length = int(handler.headers.get("Content-Length", "0"))
            if not 0 < length <= MAX_BODY:
                raise BudgetExceeded("Request exceeds the 48 MiB upload limit")
            handler.connection.settimeout(30)
            raw = handler.rfile.read(length)
            if len(raw) != length:
                raise ValueError("Incomplete request body")
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError("Request must be a JSON object")
            if parts == ["api", "regions", "jobs"]:
                base, texture = _image(data["base"], store.max_pixels), _image(data["texture"], store.max_pixels)
                masks = _masks(data["masks"], base.shape[:2]) if data.get("masks") else {}
                profile = data.get("profile", "luxury_apparel")
                if profile not in PROFILES:
                    raise ValueError("Unknown region profile")
                manifest = store.create(base, texture, masks=masks, blend=PROFILES[profile],
                                        label=data.get("label", "Untitled"), profile=profile)
                _json(handler, 201, _public(manifest))
            elif len(parts) in (5, 7) and parts[:3] == ["api", "regions", "jobs"] and parts[4] == "generations":
                queue = getattr(handler.server, "generation_queue", None)
                if queue is None:
                    _json(handler, 503, {"error": "Generation is not configured; no generation submitted"})
                elif len(parts) == 5:
                    _json(handler, 202, queue.enqueue(parts[3], data.get("expected_revision")))
                elif parts[6] in ("cancel", "resume"):
                    operation = queue.cancel if parts[6] == "cancel" else queue.resume
                    _json(handler, 200, operation(parts[3], parts[5]))
                else:
                    _json(handler, 404, {"error": "Unknown generation operation"})
            elif len(parts) == 5 and parts[:3] == ["api", "regions", "jobs"] and parts[4] == "reblend":
                values = data.get("blend")
                if not isinstance(values, dict):
                    raise ValueError("A blend object is required")
                manifest = store.reblend(parts[3], expected_revision=data.get("expected_revision"),
                                         blend=RegionBlend(**values), strokes=data.get("strokes"))
                _json(handler, 200, _public(manifest))
            elif len(parts) == 5 and parts[:3] == ["api", "regions", "jobs"] and parts[4] == "delete":
                store.delete(parts[3])
                _json(handler, 200, {"deleted": parts[3]})
            else:
                _json(handler, 404, {"error": "Unknown workspace endpoint"})
        else:
            _json(handler, 405, {"error": "Method not allowed"})
    except (BrokenPipeError, ConnectionResetError):
        return True
    except RevisionConflict as error:
        _json(handler, 409, {"error": str(error)})
    except BudgetExceeded as error:
        _json(handler, 413, {"error": str(error)})
    except PermissionError as error:
        _json(handler, 403, {"error": str(error)})
    except KeyError:
        _json(handler, 404, {"error": "Job or required input not found"})
    except (ValueError, TypeError, OSError, zipfile.BadZipFile) as error:
        _json(handler, 400, {"error": str(error)})
    return True
