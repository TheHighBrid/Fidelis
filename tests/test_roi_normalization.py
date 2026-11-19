"""Regression tests for ROI scale, clipping, and protection metadata."""
import unittest

from fidelis.eval.roi_normalization import normalize_rois_to_target


class RoiNormalizationTests(unittest.TestCase):
    def test_scaled_and_clipped_roi_preserves_metadata(self):
        entry = {"id": "logo", "kind": "logo", "bbox": [-2, 2, 8, 6], "override": "lock"}
        result = normalize_rois_to_target([entry], (40, 40), (10, 10))
        self.assertEqual(result[0]["rect"], [0, 8, 32, 16])
        self.assertEqual(result[0]["policy"], "preserve")
        self.assertEqual(result[0]["override"], "lock")

    def test_invalid_regions_are_skipped_and_duplicate_ids_remain_unique(self):
        rect = {"id": "fabric", "kind": "fabric", "rect": [1, 1, 2, 3]}
        result = normalize_rois_to_target([None, rect, rect, {"bbox": [2, 2, 1, 1]}], (10, 10))
        self.assertEqual([item["id"] for item in result], ["fabric", "fabric_2"])
        self.assertEqual([item["rect"] for item in result], [[1, 1, 2, 3]] * 2)

    def test_target_space_does_not_scale(self):
        result = normalize_rois_to_target([{"rect": [1, 2, 3, 4]}], (40, 40), (10, 10), "target")
        self.assertEqual(result[0]["rect"], [1, 2, 3, 4])
        self.assertEqual(result[0]["policy"], "texture_allowed")

    def test_unknown_coordinate_space_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unsupported roi_space"):
            normalize_rois_to_target([{"rect": [1, 2, 3, 4]}], (10, 10), roi_space="bad")
