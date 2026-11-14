"""Saved batch exports survive interruption and fail closed on stale inputs."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
from PIL import Image

from fidelis.postprocess.regions import RegionBlend
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

    def test_mixed_depth_batch_preserves_locks_and_pins_export_depth(self):
        import cv2

        protected = np.zeros(self.pixels.shape[:2], dtype=np.float32)
        protected[:, :10] = 1
        coverage = np.ones_like(protected)
        job = self.store.create(self.pixels, 255 - self.pixels,
                                masks={"protected": protected, "skin": coverage, "confidence": coverage},
                                blend=RegionBlend(skin=.5))
        recipe = [self.recipe[0], {"job_id": job["id"], "revision": 1,
                                   "filename": "master.png", "depth": 16}]
        batch.export_batch(self.store, recipe, self.destination, 100000)
        path = self.destination / "master.png"
        actual = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)[:, :, ::-1]
        self.assertEqual(actual.dtype, np.uint16)
        np.testing.assert_array_equal(actual[:, :10], self.pixels[:, :10].astype(np.uint16) * 257)
        self.assertTrue(np.any(actual[:, 10:] % 257))
        with Image.open(self.destination / "0.png") as image:
            self.assertEqual(np.asarray(image).dtype, np.uint8)
        self.assertEqual(batch.export_batch(self.store, recipe, self.destination, 100000)[1]["status"], "reused")
        with self.assertRaisesRegex(ValueError, "receipt does not match"):
            batch.export_batch(self.store, [{**recipe[1], "depth": 8}], self.destination, 100000)

    def test_releases_previous_master_before_opening_next(self):
        from contextlib import contextmanager
        import weakref

        original = self.store.open_master16
        previous = None

        @contextmanager
        def tracked_open(*args):
            nonlocal previous
            if previous is not None:
                self.assertIsNone(previous())
            with original(*args) as master:
                previous = weakref.ref(master)
                yield master

        self.store.open_master16 = tracked_open
        batch.export_batch(self.store, [{**item, "depth": 16} for item in self.recipe],
                           self.destination, 100000)

    def test_interrupted_staging_counts_against_output_budget(self):
        orphan = self.destination / ".fidelis-export-interrupted"
        orphan.mkdir(parents=True)
        (orphan / "master.png").write_bytes(b"x" * 15000)
        with self.assertRaisesRegex(ValueError, "budget"):
            batch.export_batch(self.store, [self.recipe[0]], self.destination, 20000)
        self.assertFalse((self.destination / "0.png").exists())
        self.assertEqual((orphan / "master.png").stat().st_size, 15000)

    def test_recovery_respects_peak_space_while_verifying_partial_png(self):
        recipe = [self.recipe[0]]
        batch.export_batch(self.store, recipe, self.destination, 25000)
        output = self.destination / "0.png"
        receipt = output.with_suffix(".png.recipe.json")
        receipt.unlink()
        limit = output.stat().st_size + 1024
        with self.assertRaisesRegex(ValueError, "budget"):
            batch.export_batch(self.store, recipe, self.destination, limit)
        self.assertTrue(output.is_file())
        self.assertFalse(receipt.exists())

    def test_never_stages_receipt_when_peak_budget_cannot_fit_it(self):
        from unittest.mock import patch

        recipe = [self.recipe[0]]
        batch.export_batch(self.store, recipe, self.destination, 25000)
        limit = (self.destination / "0.png").stat().st_size
        destination = self.destination / "tight"
        with patch.object(Path, "write_bytes", side_effect=AssertionError("staged oversized receipt")), \
             patch.object(Path, "write_text", side_effect=AssertionError("staged oversized receipt")):
            with self.assertRaisesRegex(ValueError, "budget"):
                batch.export_batch(self.store, recipe, destination, limit)
        self.assertEqual(list(destination.glob("*.png")), [])

    def test_explicit_rgb8_reuses_legacy_receipt(self):
        batch.export_batch(self.store, [self.recipe[0]], self.destination, 20000)
        receipt = self.destination / "0.png.recipe.json"
        evidence = json.loads(receipt.read_text())
        evidence.pop("depth")
        receipt.write_text(json.dumps(evidence))
        result = batch.export_batch(self.store, [{**self.recipe[0], "depth": 8}], self.destination, 20000)
        self.assertEqual(result[0]["status"], "reused")

    def test_invalid_depth_fails_before_any_export(self):
        with self.assertRaisesRegex(ValueError, "depth"):
            batch.export_batch(self.store, [self.recipe[0], {**self.recipe[1], "depth": True}],
                               self.destination, 100000)
        self.assertFalse(self.destination.exists())

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
