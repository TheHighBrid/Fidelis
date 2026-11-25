"""Native-grid paired weave spectra retain the established material criteria."""

import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import numpy as np

from fidelis.eval import material_metrics, spectral_memory


class WeaveMemoryTests(unittest.TestCase):
    def reference(self, a, b):
        return material_metrics._weave_spectrum(a, b, *a.shape)

    def bounded(self, a, b, **kwargs):
        a = a - float(np.mean(a))
        b = b - float(np.mean(b))
        return spectral_memory.spectral_weave_coherence(a, b, **kwargs)

    def test_rectangles_noncontiguous_views_and_block_sizes(self):
        rng = np.random.default_rng(129)
        for shape in ((1, 1), (1, 7), (4, 4), (17, 24), (32, 19), (63, 65)):
            a = rng.normal(50, 10, shape).astype(np.float32)
            b = (a * .8 + rng.normal(0, 2, shape)).astype(np.float32)
            for left, right in ((a, b), (a[::-1, ::-1], b[::-1, ::-1])):
                expected = self.reference(left, right)
                for block in ((1, 7, 128) if a.size <= 17 * 24 else (7, 128)):
                    with self.subTest(shape=shape, block=block):
                        np.testing.assert_allclose(
                            self.bounded(left, right, block_size=block),
                            expected, rtol=3e-6, atol=3e-7,
                        )

    def test_zero_constant_and_identity(self):
        rng = np.random.default_rng(3)
        for a in (np.zeros((31, 40), np.float32), np.full((31, 40), 60, np.float32),
                  rng.normal(size=(31, 40)).astype(np.float32)):
            actual = self.bounded(a, a, block_size=11)
            np.testing.assert_allclose(actual, self.reference(a, a), rtol=3e-6, atol=3e-7)
            self.assertTrue(actual[0] >= .75 and actual[1] >= .90)

    def test_large_float32_norm_retains_reference_precision(self):
        rng = np.random.default_rng(131)
        a = rng.normal(80, 10, (1024, 1536)).astype(np.float32)
        b = a + rng.normal(0, 1, a.shape).astype(np.float32)
        expected = self.reference(a, b)
        actual = self.bounded(a, b)
        self.assertEqual(actual, expected)

    def test_energy_threshold_neighborhood(self):
        a = np.random.default_rng(8).normal(size=(43, 57)).astype(np.float32)
        for energy in (.8998, .9002):
            b = a * np.float32(np.sqrt(energy))
            old = self.reference(a, b)
            new = self.bounded(a, b, block_size=9)
            self.assertEqual(old[1] >= .90, new[1] >= .90)
            np.testing.assert_allclose(new, old, rtol=3e-6, atol=3e-7)

    def test_coherence_threshold_neighborhood(self):
        rng = np.random.default_rng(12)
        a = rng.normal(size=(47, 59)).astype(np.float32)
        noise = rng.normal(size=a.shape).astype(np.float32)
        for target in (.7498, .7502):
            low, high = 0., 1.
            for _ in range(24):
                alpha = (low + high) / 2
                b = (a * (1 - alpha) + noise * alpha).astype(np.float32)
                if self.reference(a, b)[0] > target:
                    low = alpha
                else:
                    high = alpha
            old = self.reference(a, b)
            new = self.bounded(a, b, block_size=13)
            self.assertAlmostEqual(old[0], target, places=5)
            self.assertEqual(old[0] >= .75, new[0] >= .75)

    def test_shape_type_and_scratch_validation(self):
        a = np.ones((4, 5), np.float32)
        for b in (a[:2], a[:, 0], np.ones((4, 5), np.float64)):
            with self.assertRaises((ValueError, TypeError)):
                self.bounded(a, b)
        with self.assertRaises(ValueError):
            self.bounded(a, a, block_size=0)
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(OSError):
                self.bounded(a, a, scratch_dir=Path(tmp) / 'missing')

    def test_fft_failure_cleans_both_power_files(self):
        a = np.ones((7, 11), np.float32)
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(spectral_memory, '_column_transform', side_effect=RuntimeError('FFT failed')):
                with self.assertRaisesRegex(RuntimeError, 'FFT failed'):
                    self.bounded(a, a, scratch_dir=tmp)
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_pair_read_failure_and_flush_failure_clean_scratch(self):
        a = np.random.default_rng(9).normal(size=(11, 13)).astype(np.float32)
        original = spectral_memory._mapped_rows

        @contextmanager
        def fail_candidate_read(path, *args, **kwargs):
            reading = kwargs.get('mode', 'r') == 'r'
            if target == 'transpose' and path.name.endswith('.transposed.dat') and reading:
                raise OSError('transpose read failed')
            if target == 'read' and path.name == 'candidate.dat' and reading:
                raise OSError('pair read failed')
            with original(path, *args, **kwargs) as rows:
                yield rows

        for target in ('read', 'transpose', 'flush'):
            with tempfile.TemporaryDirectory() as tmp:
                mocking = (patch.object(spectral_memory, '_mapped_rows', fail_candidate_read)
                           if target in ('read', 'transpose') else patch.object(np.memmap, 'flush', side_effect=OSError('disk full')))
                with mocking, self.assertRaises(OSError):
                    self.bounded(a, a, scratch_dir=tmp)
                self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_material_integration_retains_report_values_and_decisions(self):
        yy, xx = np.mgrid[:81, :109].astype(np.float32)
        a = (128 + 40 * np.sin((xx + yy) * .8)).astype(np.float32)
        b = (128 + 40 * np.sin((xx - yy) * .8)).astype(np.float32)
        roi = {'id': 'weave', 'rect': [0, 0, 109, 81]}
        for candidate in (a, b, a * .94):
            old = material_metrics._fabric_report(roi, candidate, a)
            with patch.object(material_metrics, '_SPECTRAL_MEMORY_THRESHOLD', 0):
                new = material_metrics._fabric_report(roi, candidate, a)
            self.assertEqual(new['passed'], old['passed'])
            for key in ('weave_orientation_coherence', 'weave_fft_coherence', 'weave_energy_ratio'):
                self.assertAlmostEqual(new[key], old[key], places=5)


if __name__ == '__main__':
    unittest.main()
