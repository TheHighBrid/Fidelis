"""Exercise upload rejection through the real HTTP handler without GPU models."""
import base64
import http.client
import http.server
import importlib.util
import io
import json
from pathlib import Path
import threading
import unittest
from unittest.mock import patch, Mock

from PIL import Image

spec = importlib.util.spec_from_file_location(
    "web_ui", Path(__file__).resolve().parents[1] / "scripts/web-ui.py"
)
web = importlib.util.module_from_spec(spec)
spec.loader.exec_module(web)


class UploadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.HTTPServer(("127.0.0.1", 0), web.FidelisRequestHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def post(self, body, path="/api/upscale", headers=None):
        conn = http.client.HTTPConnection(*self.server.server_address, timeout=5)
        try:
            conn.request("POST", path, body, headers or {})
            response = conn.getresponse()
            return response.status, json.loads(response.read())
        finally:
            conn.close()

    def test_invalid_requests_are_client_errors(self):
        for body in (b"", b"{", b"\xff", b"[]", b"null", b"{}",
                     b'{"image":5}', b'{"image":"@@@"}',
                     b'{"image":"bm90IGFuIGltYWdl"}'):
            for path in web.IMAGE_ENDPOINTS:
                with self.subTest(body=body, path=path):
                    status, data = self.post(body, path)
                    self.assertEqual(status, 400)
                    self.assertIn("error", data)

    def test_oversized_request_rejected_before_read(self):
        status, _ = self.post(b"{}", headers={"Content-Length": str(web.MAX_REQUEST_BYTES + 1)})
        self.assertEqual(status, 413)

    def test_bad_length(self):
        status, _ = self.post(b"{}", headers={"Content-Length": "invalid"})
        self.assertEqual(status, 400)

    def image_data(self, fmt):
        stream = io.BytesIO()
        Image.new("RGB", (8, 8), "red").save(stream, format=fmt)
        return stream.getvalue()

    def test_supported_formats_preserve_original_bytes(self):
        for fmt in ("PNG", "JPEG", "WEBP"):
            payload = self.image_data(fmt)
            encoded = base64.b64encode(payload).decode()
            for value in (encoded, "data:image/" + fmt.lower() + ";base64," + encoded):
                self.assertEqual(web.decode_upload({"image": value}), payload)

    def test_pixel_limit_and_unsupported_format(self):
        encoded = base64.b64encode(self.image_data("PNG")).decode()
        with patch.object(web, "MAX_IMAGE_PIXELS", 16):
            status, _ = self.post(json.dumps({"image": encoded}))
            self.assertEqual(status, 413)
        encoded = base64.b64encode(self.image_data("GIF")).decode()
        status, _ = self.post(json.dumps({"image": encoded}))
        self.assertEqual(status, 400)

    def test_calibration_accepts_empty_body(self):
        engine = Mock()
        engine.run_self_improvement_cycle.return_value = {"quality_status": "tested"}
        with patch.object(web, "SelfImprovementEngine", return_value=engine, create=True):
            for body in (b"", b"{}"):
                status, data = self.post(body, "/api/self-improve/run")
                self.assertEqual(status, 200)
                self.assertEqual(data["quality_status"], "tested")

    def test_rejected_audition_keeps_previous_results(self):
        with patch.object(web.shutil, "rmtree") as remove:
            self.post(b'{"image":"@@@"}', "/api/audition")
            remove.assert_not_called()


if __name__ == "__main__":
    unittest.main()
