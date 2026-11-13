"""Saved batch exports survive interruption and fail closed on stale inputs."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
from PIL import Image

from fidelis.studio.store import JobStore, RevisionConflict

spec = importlib.util.spec_from_file_location(
    "studio_batch_export", Path(__file__).resolve().parents[1] / "scripts/export-studio-batch.py")
batch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(batch)


class BatchExportTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.store = JobStore(root / "workspace")
        self.destination = root / "deliverables"
        self.pixels = np.random.default_rng(14).integers(0, 256, (52, 74, 3), np.uint8)
        self.jobs = [self.store.create(self.pixels, self.pixels) for _ in range(2)]
        self.recipe = [{"job_id": job["id"], "revision": 1, "filename": f"{i}.png"}
                       for i, job in enumerate(self.jobs)]

    def test_resume_after_budget_failure_verifies_and_reuses_png(self):
        with self.assertRaisesRegex(ValueError, "budget"):
            batch.export_batch(self.store, self.recipe, self.destination, 16000)
        first, second = [self.destination / item["filename"] for item in self.recipe]
        self.assertTrue(first.is_file())
        self.assertFalse(second.exists())
        initial_inode = first.stat().st_ino
        receipt = first.with_suffix(".png.recipe.json")
        receipt.unlink()  # Simulate interruption between PNG and receipt publication.
        self.assertEqual(batch.export_batch(self.store, self.recipe, self.destination, 30000)[0]["status"],
                         "exported")
        self.assertEqual(first.stat().st_ino, initial_inode)
        result = batch.export_batch(self.store, self.recipe, self.destination, 30000)
        self.assertEqual([item["status"] for item in result], ["reused", "reused"])
        self.assertFalse(json.loads(receipt.read_text())["inference_executed"])
        with Image.open(second) as image:
            np.testing.assert_array_equal(np.asarray(image), self.pixels)
        first.write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "receipt does not match"):
            batch.export_batch(self.store, self.recipe, self.destination, 30000)

    def test_stale_revision_and_unsafe_filenames_fail_without_publishing(self):
        recipe = [{**self.recipe[0], "filename": "../outside.png"}]
        with self.assertRaisesRegex(ValueError, "basename"):
            batch.export_batch(self.store, recipe, self.destination, 30000)
        recipe = [{**self.recipe[0], "revision": 2}]
        with self.assertRaises(RevisionConflict):
            batch.export_batch(self.store, recipe, self.destination, 30000)
        self.assertEqual(list(self.destination.glob("*.png")), [])


if __name__ == "__main__":
    unittest.main()
