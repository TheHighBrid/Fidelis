"""Thread-safe local ComfyUI fixture HTTP server for F07 async queue qualification."""

from __future__ import annotations

import http.server
import io
import json
import socketserver
import threading
import time
from typing import Any

import numpy as np
from PIL import Image


def png_bytes(array: np.ndarray) -> bytes:
    """Encode an RGB uint8 array into PNG bytes."""
    buf = io.BytesIO()
    Image.fromarray(array).save(buf, format="PNG")
    return buf.getvalue()


def _parse_query_filename(path: str) -> str:
    query = path.split("?", 1)[1] if "?" in path else ""
    for part in query.split("&"):
        if part.startswith("filename="):
            return part.split("=", 1)[1]
    return ""


def _extract_upload_payload(body: bytes) -> tuple[str, bytes]:
    marker = b'filename="'
    start = body.find(marker)
    name = "uploaded.png"
    if start != -1:
        end = body.find(b'"', start + len(marker))
        name = body[start + len(marker) : end].decode("utf-8", "ignore")
    png_start = body.find(b"\x89PNG\r\n\x1a\n")
    png_end = body.rfind(b"IEND\xaeB`\x82")
    return name, body[png_start : png_end + 8]


class _MockComfyHandler(http.server.BaseHTTPRequestHandler):
    """Minimal loopback HTTP handler simulating ComfyUI endpoints."""

    parent: MockComfyServer

    def log_message(self, *args: Any) -> None:
        return None

    def _send_json(self, code: int, payload: Any) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_png(self, blob: bytes | None) -> None:
        if blob is None:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(blob)))
        self.end_headers()
        self.wfile.write(blob)

    def do_GET(self) -> None:
        if self.path == "/system_stats":
            self._send_json(200, {"system": {"comfyui_version": "fixture-0.1"}})
            return
        if self.path == "/object_info":
            self._send_json(200, _OBJECT_INFO_PAYLOAD)
            return
        if self.path == "/queue":
            self._send_json(200, self.parent.queue_snapshot())
            return
        if self.path.startswith("/history/"):
            pid = self.path.split("/history/", 1)[1].split("?", 1)[0]
            self._send_json(200, self.parent.history_snapshot(pid))
            return
        if self.path.startswith("/view"):
            fname = _parse_query_filename(self.path)
            self._send_png(self.parent.get_output(fname))
            return
        self.send_response(404)
        self.end_headers()

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        if self.path == "/interrupt":
            self.parent.record_interrupt()
            self._send_json(200, {})
            return
        if self.path == "/upload/image":
            name, raw_png = _extract_upload_payload(body)
            self.parent.store_upload(name, raw_png)
            self._send_json(200, {"name": name, "subfolder": "", "type": "input"})
            return
        if self.path == "/prompt":
            payload = json.loads(body.decode("utf-8"))
            pid = self.parent.submit_prompt(payload["prompt"])
            self._send_json(200, {"prompt_id": pid})
            return
        self.send_response(404)
        self.end_headers()


_OBJECT_INFO_PAYLOAD: dict[str, Any] = {
    "LoadImage": {"input": {"required": {"image": [["in.png"]]}}},
    "FixtureTexture": {"input": {"required": {"image": ["IMAGE"]}}},
    "SaveImage": {
        "input": {"required": {"images": ["IMAGE"], "filename_prefix": ["STRING"]}}
    },
}


class MockComfyServer:
    """Thread-safe local ComfyUI fixture server for `--fixture` mode."""

    def __init__(self, delay_seconds: float = 0.8) -> None:
        self.delay_seconds = delay_seconds
        self._lock = threading.Lock()
        self._uploads: dict[str, bytes] = {}
        self._prompts: dict[str, dict[str, Any]] = {}
        self._outputs: dict[str, bytes] = {}
        self.interrupt_calls = 0
        self.prompt_submissions = 0
        self._prompt_counter = 0
        self._server: socketserver.ThreadingTCPServer | None = None
        self._thread: threading.Thread | None = None
        self.address = ""

    def queue_snapshot(self) -> dict[str, Any]:
        now = time.monotonic()
        with self._lock:
            running = [
                [0, pid, entry["prompt"]]
                for pid, entry in self._prompts.items()
                if now < entry["done_at"]
            ]
        return {"queue_running": running, "queue_pending": []}

    def history_snapshot(self, pid: str) -> dict[str, Any]:
        now = time.monotonic()
        with self._lock:
            entry = self._prompts.get(pid)
            ready = entry is not None and now >= entry["done_at"]
        if not ready or entry is None:
            return {}
        return {
            pid: {
                "prompt": [0, pid, entry["prompt"]],
                "status": {"status_str": "success", "completed": True},
                "outputs": {
                    "3": {
                        "images": [
                            {"filename": f"{pid}.png", "subfolder": "", "type": "output"}
                        ]
                    }
                },
            }
        }

    def get_output(self, fname: str) -> bytes | None:
        with self._lock:
            return self._outputs.get(fname)

    def record_interrupt(self) -> None:
        with self._lock:
            self.interrupt_calls += 1

    def store_upload(self, name: str, raw_png: bytes) -> None:
        with self._lock:
            self._uploads[name] = raw_png

    def submit_prompt(self, prompt: dict[str, Any]) -> str:
        img_name = prompt["1"]["inputs"]["image"]
        with self._lock:
            self._prompt_counter += 1
            self.prompt_submissions += 1
            pid = f"fix-prompt-{self._prompt_counter:04d}"
            raw_png = self._uploads[img_name]
            with Image.open(io.BytesIO(raw_png)) as im:
                arr = np.asarray(im.convert("RGB"), dtype=np.uint8)
            out_arr = np.clip(arr.astype(np.int16) + 25, 0, 255).astype(np.uint8)
            self._outputs[f"{pid}.png"] = png_bytes(out_arr)
            self._prompts[pid] = {
                "prompt": prompt,
                "done_at": time.monotonic() + self.delay_seconds,
            }
        return pid

    def __enter__(self) -> MockComfyServer:
        server_ref = self

        class BoundHandler(_MockComfyHandler):
            parent = server_ref

        socketserver.ThreadingTCPServer.allow_reuse_address = True
        self._server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), BoundHandler)
        self.address = f"http://127.0.0.1:{self._server.server_address[1]}"
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *args: Any) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=3)
