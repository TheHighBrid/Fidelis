"""Offline regression tests for optional public research ingestion."""
import importlib.util
import io
import json
import unittest
from pathlib import Path
from urllib.error import HTTPError


PATH = Path(__file__).resolve().parents[1] / "scripts" / "contextdev-research.py"
spec = importlib.util.spec_from_file_location("fidelis_contextdev_research", PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ContextDevResearchTests(unittest.TestCase):
    def test_partial_formats_and_pending_rights(self):
        requests = []
        def fake(request, *, timeout):
            requests.append(json.loads(request.data))
            self.assertTrue(request.get_header("Authorization").startswith("Bearer "))
            self.assertLessEqual(timeout, 20)
            return io.BytesIO(json.dumps({
                "url": "https://models.example.org/demo",
                "isPartial": True,
                "json": {"requested": True, "success": False, "data": None, "error_code": "NO_DATA"},
                "markdown": {"requested": True, "success": True, "data": "# Model card"},
            }).encode())
        result = module.scrape("https://models.example.org/demo", api_key="offline-test", request_fn=fake)
        self.assertTrue(result["is_partial"])
        self.assertEqual(result["formats"]["markdown"]["data"], "# Model card")
        self.assertEqual(result["formats"]["json"]["error_code"], "NO_DATA")
        self.assertEqual(result["candidate_status"], "pending_review")
        self.assertFalse(result["rights_cleared_for_benchmark"])
        self.assertFalse(result["publisher_results_locally_verified"])
        self.assertEqual(requests[0]["maxAgeMs"], 86_400_000)
        self.assertEqual(requests[0]["timeoutOpts"]["milliseconds"], 20000)

    def test_retry_once_transient_only(self):
        attempts = []
        def fake(request, *, timeout):
            attempts.append(1)
            if len(attempts) == 1:
                raise HTTPError(request.full_url, 503, "temporary", {}, None)
            return io.BytesIO(json.dumps({
                "json": {"requested": True, "success": True, "data": {"name": "Fixture"}},
                "markdown": {"requested": True, "success": True, "data": "Fixture"},
            }).encode())
        result = module.scrape("https://models.example.org/demo", api_key="offline", request_fn=fake)
        self.assertEqual(len(attempts), 2)
        self.assertEqual(result["extracted"]["name"], "Fixture")

    def test_zdr_highlights_conflict(self):
        with self.assertRaisesRegex(ValueError, "incompatible"):
            module.scrape("https://models.example.org/demo", api_key="offline", highlights=True, zdr=True)

    def test_private_urls_blocked(self):
        for url in ("http://127.0.0.1", "https://10.2.3.4", "http://localhost", "file:///etc/passwd",
                    "https://user:pw@example.org", "http://internal.local"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                module.public_url(url)

    def test_highlights_query_is_bounded(self):
        calls = []
        def fake(request, *, timeout):
            calls.append(json.loads(request.data))
            return io.BytesIO(json.dumps({
                "json": {"requested": True, "success": True, "data": {}},
                "markdown": {"requested": True, "success": True, "data": ""},
                "highlights": {"requested": True, "success": True, "data": ["MIT license"]},
            }).encode())
        module.scrape("https://models.example.org/demo", api_key="offline",
                      highlights=True, request_fn=fake)
        self.assertEqual(calls[0]["highlightsParams"]["maxCharacters"], 2000)
        self.assertEqual(calls[0]["formats"]["highlights"], True)


if __name__ == "__main__":
    unittest.main()
