"""Regression coverage for paired legacy calibration fixtures."""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import cv2
import numpy as np

from fidelis.eval.corpus import EvaluationCorpus


class CalibrationPairAlignmentTest(unittest.TestCase):
    def test_odd_sized_seed_produces_exact_fourfold_pairs(self):
        with TemporaryDirectory() as root:
            corpus_dir = Path(root)
            source = np.arange(67 * 73 * 3, dtype=np.uint8).reshape(67, 73, 3)
            seed = corpus_dir / "seed.png"
            self.assertTrue(cv2.imwrite(str(seed), source))
            corpus = EvaluationCorpus(corpus_dir)
            corpus.items = [item for item in corpus.items if item.source_path == str(seed)]

            pairs = [item for item in corpus.ensure_minimum_corpus() if item.is_paired]

            self.assertTrue(pairs)
            for item in pairs:
                with self.subTest(bucket=item.bucket):
                    low = cv2.imread(item.source_path)
                    reference = cv2.imread(item.ground_truth_path)
                    self.assertEqual(reference.shape[:2], (4 * item.height, 4 * item.width))
                    self.assertEqual(low.shape[:2], (item.height, item.width))
                    np.testing.assert_array_equal(reference, source[:64, :72])

    def test_small_seed_is_kept_but_a_later_eligible_seed_is_used(self):
        with TemporaryDirectory() as root:
            corpus_dir = Path(root)
            small = corpus_dir / "small.png"
            eligible = corpus_dir / "eligible.png"
            self.assertTrue(cv2.imwrite(str(small), np.zeros((63, 80, 3), dtype=np.uint8)))
            source = np.full((64, 80, 3), 100, dtype=np.uint8)
            self.assertTrue(cv2.imwrite(str(eligible), source))
            corpus = EvaluationCorpus(corpus_dir)
            local = {item.source_path: item for item in corpus.items}
            corpus.items = [local[str(small)]]

            self.assertEqual(corpus.ensure_minimum_corpus(), [local[str(small)]])
            self.assertEqual(len(list(corpus_dir.rglob("syn_*.png"))), 0)

            corpus.items.append(local[str(eligible)])
            items = corpus.ensure_minimum_corpus()
            self.assertIn(local[str(small)], items)
            pairs = [item for item in items if item.is_paired]
            self.assertTrue(pairs)
            for item in pairs:
                self.assertEqual((item.height, item.width), (16, 20))
                np.testing.assert_array_equal(cv2.imread(item.ground_truth_path), source)


if __name__ == "__main__":
    unittest.main()
