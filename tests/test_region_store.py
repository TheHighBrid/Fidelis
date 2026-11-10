"""Persistent artifact contracts, failure recovery and bounded composition."""
import io
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from pathlib import Path
import sqlite3
import tempfile
import unittest

import numpy as np
from PIL import Image

from fidelis.postprocess.regions import RegionBlend, compose_regions
from fidelis.studio.store import BudgetExceeded, JobStore, RevisionConflict, write_rgb_png


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.base = np.random.default_rng(16).integers(0, 256, (17, 23, 3), dtype=np.uint8)
        self.texture = 255 - self.base
        self.masks = {'skin': np.ones((17, 23), np.float32),
                      'confidence': np.ones((17, 23), np.float32)}
        self.store = JobStore(self.root, workspace_budget=23 * 256 * 3)

    def create(self):
        return self.store.create(self.base, self.texture, masks=self.masks)

    def test_restart_reload_and_striped_reblend_match_reference(self):
        job = self.create()
        store = JobStore(self.root, workspace_budget=23 * 256)
        blend = RegionBlend(.6, .3, .2)
        result = store.reblend(job['id'], expected_revision=1, blend=blend)
        self.assertEqual(result['revision'], 2)
        with store.open_array(job['id'], 'master') as actual:
            expected, _ = compose_regions(self.base, self.texture, blend=blend, **self.masks)
            np.testing.assert_array_equal(actual, expected)
        self.assertEqual(store.get(job['id'])['blend']['skin'], .6)
        self.assertEqual(len(store.list()), 1)

    def test_stale_revision_does_not_change_saved_job(self):
        job = self.create()
        self.store.reblend(job['id'], expected_revision=1, blend=RegionBlend(.7))
        with self.assertRaises(RevisionConflict):
            self.store.reblend(job['id'], expected_revision=1, blend=RegionBlend(.2))
        self.assertEqual(self.store.get(job['id'])['revision'], 2)

    def test_disk_budget_fails_without_publishing_partial_job(self):
        limited = JobStore(self.root / 'limited', disk_budget=200)
        with self.assertRaises(BudgetExceeded):
            limited.create(self.base, self.texture, masks=self.masks)
        self.assertEqual(limited.list(), [])
        self.assertEqual(list((limited.root / 'artifacts').glob('*.npy')), [])

    def test_revision_budget_keeps_previous_export(self):
        job = self.create()
        self.store.disk_budget = sum(p.stat().st_size for p in (self.root / 'artifacts').glob('*.npy'))
        with self.assertRaises(BudgetExceeded):
            self.store.reblend(job['id'], expected_revision=1, blend=RegionBlend(.7))
        self.assertEqual(self.store.get(job['id'])['revision'], 1)
        with self.store.open_array(job['id'], 'master') as image:
            self.assertEqual(image.shape, self.base.shape)

    def test_corruption_fails_before_render(self):
        job = self.create()
        path = self.root / job['artifacts']['texture']['path']
        with path.open('ab') as stream:
            stream.write(b'tampered')
        with self.assertRaisesRegex(ValueError, 'checksum'):
            self.store.reblend(job['id'], expected_revision=1, blend=RegionBlend())
        self.assertEqual(self.store.get(job['id'])['revision'], 1)

    def test_restart_discards_uncommitted_artifacts_only(self):
        job = self.create()
        abandoned = self.root / 'artifacts' / 'abandoned.npy'
        abandoned.write_bytes(b'incomplete')
        JobStore(self.root)
        self.assertFalse(abandoned.exists())
        self.assertTrue((self.root / job['artifacts']['base']['path']).is_file())

    def test_delete_reclaims_artifacts(self):
        job = self.create()
        self.store.delete(job['id'])
        self.assertEqual(self.store.list(), [])
        self.assertEqual(list((self.root / 'artifacts').glob('*.npy')), [])

    def test_unknown_schema_and_job_paths_rejected(self):
        with self.assertRaises(KeyError):
            self.store.get('../../secrets')
        with sqlite3.connect(self.root / 'jobs.sqlite3') as db:
            db.execute('PRAGMA user_version=999')
        with self.assertRaisesRegex(ValueError, 'schema'):
            JobStore(self.root)

    def test_replaced_masks_and_zero_confidence_protect_base(self):
        job = self.create()
        self.store.reblend(job['id'], expected_revision=1, blend=RegionBlend(1), masks={})
        with self.store.open_array(job['id'], 'master') as actual:
            np.testing.assert_array_equal(actual, self.base)

    def test_concurrent_stores_cannot_commit_the_same_revision(self):
        job = self.create()
        other = JobStore(self.root)
        def attempt(store):
            try:
                store.reblend(job['id'], expected_revision=1, blend=RegionBlend(.5))
                return 'saved'
            except RevisionConflict:
                return 'conflict'
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(attempt, (self.store, other)))
        self.assertCountEqual(results, ['saved', 'conflict'])
        self.assertEqual(self.store.get(job['id'])['revision'], 2)

    def test_render_failure_rolls_back_masks_and_cleans_candidate_files(self):
        job = self.create()
        before = set((self.root / 'artifacts').glob('*.npy'))
        with patch.object(self.store, '_render', side_effect=OSError('Disk full')):
            with self.assertRaisesRegex(OSError, 'Disk full'):
                self.store.reblend(job['id'], expected_revision=1, blend=RegionBlend(.5),
                                   masks={'skin': self.masks['skin'] * .4})
        self.assertEqual(self.store.get(job['id'])['revision'], 1)
        self.assertEqual(set((self.root / 'artifacts').glob('*.npy')), before)
        with self.store.open_array(job['id'], 'master') as actual:
            expected, _ = compose_regions(self.base, self.texture, **self.masks)
            np.testing.assert_array_equal(actual, expected)

    def test_streaming_png_roundtrip(self):
        encoded = io.BytesIO()
        write_rgb_png(self.base, encoded)
        with Image.open(io.BytesIO(encoded.getvalue())) as image:
            np.testing.assert_array_equal(np.array(image), self.base)
            self.assertEqual(image.info['srgb'], 0)

    def test_pixel_and_scanline_budgets(self):
        for store in (JobStore(self.root / 'pixels', max_pixels=10),
                      JobStore(self.root / 'rows', workspace_budget=1)):
            with self.assertRaises(BudgetExceeded):
                store.create(self.base, self.texture)
            self.assertEqual(store.list(), [])


if __name__ == '__main__':
    unittest.main()
