"""Regression tests for MEL-73: unsigned provenance must never claim C2PA verification."""
import ast
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fidelis.core.provenance import generate_c2pa_provenance

SOURCE = Path(__file__).resolve().parents[1] / "fidelis" / "core" / "pipeline.py"


class UnsignedProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.input = Path(self.tmp.name) / "input.png"
        self.output = Path(self.tmp.name) / "output.png"
        self.input.write_bytes(b"input image")
        self.output.write_bytes(b"output image")

    def generate(self):
        return generate_c2pa_provenance(
            self.input, self.output, "luxury_apparel", 4, 512,
            hashlib.sha256(self.output.read_bytes()).hexdigest(),
        )

    def test_unsigned_sidecar_has_honest_status_and_hashes(self):
        claim = self.generate()
        saved = json.loads(self.output.with_suffix(".png.c2pa.json").read_text())
        self.assertEqual(claim, saved)
        self.assertEqual(saved["signature_info"]["status"], "unsigned")
        self.assertIsNone(saved["signature_info"]["issuer"])
        self.assertNotEqual(saved["format"], "application/x-c2pa-manifest-1.3")
        hashes = saved["assertions"][1]["data"]
        self.assertEqual(hashes["input_sha256"], hashlib.sha256(b"input image").hexdigest())
        self.assertEqual(hashes["output_sha256"], hashlib.sha256(b"output image").hexdigest())

    def test_failed_sidecar_write_is_reported_not_verified(self):
        original_open = open

        def fail_sidecar(path, *args, **kwargs):
            if str(path).endswith(".c2pa.json"):
                raise PermissionError("read-only destination")
            return original_open(path, *args, **kwargs)

        with patch("builtins.open", side_effect=fail_sidecar):
            claim = self.generate()
        self.assertEqual(claim["signature_info"]["status"], "write_failed")
        self.assertFalse(self.output.with_suffix(".png.c2pa.json").exists())

    def test_pipeline_telemetry_and_result_use_actual_provenance_status(self):
        source = SOURCE.read_text(encoding="utf-8")
        tree = ast.parse(source)
        pipeline = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "UpscalePipeline")
        run = next(node for node in pipeline.body if isinstance(node, ast.FunctionDef) and node.name == "run")
        literals = [node.value for node in ast.walk(run) if isinstance(node, ast.Constant) and isinstance(node.value, str)]
        self.assertNotIn("verified", literals)
        self.assertGreaterEqual(source.count('c2pa_claim["signature_info"]["status"]'), 3)


if __name__ == "__main__":
    unittest.main()
