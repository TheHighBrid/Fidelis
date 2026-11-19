"""Regression checks for pipeline reference and unavailable quality contracts."""
import unittest
from unittest.mock import patch

import numpy as np
from fidelis.eval.pipeline_metrics import measure_pipeline_metrics


class PipelineRoutingTests(unittest.TestCase):
    def setUp(self):
        self.image = np.zeros((3, 4, 3), dtype=np.uint8)

    def test_missing_reference_and_output_remain_unavailable(self):
        for source, output, kwargs, reason in (
            (self.image, None, {}, 'output_decode_unavailable'),
            (None, self.image, {}, 'source_decode_unavailable'),
            (self.image, self.image, {'ground_truth_requested': True}, 'ground_truth_decode_unavailable'),
            (self.image, self.image, {'ground_truth_requested': True,
             'ground_truth_bgr': self.image[:1]}, 'ground_truth_dimensions_mismatch'),
        ):
            with self.subTest(reason=reason):
                metrics, context = measure_pipeline_metrics(source, output, **kwargs)
                self.assertEqual(context['reason'], reason)
                self.assertTrue(all(value is None for value in metrics.values()))

    @patch('fidelis.eval.pipeline_metrics.measure_scale_matched_metrics')
    def test_scale_matched_unavailable_is_not_a_pass(self, measure):
        measure.return_value = {'status': 'unavailable', 'reason': 'test_unavailable'}
        metrics, context = measure_pipeline_metrics(self.image, self.image, rois=[])
        self.assertEqual(context['reference'], 'bicubic_scale_matched')
        self.assertEqual(context['reason'], 'test_unavailable')
        self.assertIsNone(metrics['all_detail_gates_passed'])
        np.testing.assert_array_equal(measure.call_args.args[1], self.image)

    @patch('fidelis.eval.pipeline_metrics.measure_scale_matched_metrics')
    def test_no_fabric_is_not_applicable_and_locks_still_gate(self, measure):
        measure.return_value = {
            'status': 'measured',
            'interior_texture': {'interior_texture_variance_ratio': 0.8, 'interior_midband_energy_ratio': 0.9},
            'oversharpening_restraint': {'contour_overshoot_p95': 0.1, 'contour_nyquist_to_midband_ratio': 0.2},
            'fabric_hardware': {'locked_pixel_mismatches': 1},
            'interior_texture_passed': True, 'oversharpen_restraint_passed': True,
            'fabric_weave_passed': True, 'all_detail_gates_passed': False,
        }
        metrics, context = measure_pipeline_metrics(self.image, self.image, bicubic_bgr=self.image)
        self.assertEqual(context['fabric_weave']['status'], 'not_applicable')
        self.assertIsNone(metrics['fabric_weave_passed'])
        self.assertIsNone(metrics['fabric_weave_coherence'])
        self.assertFalse(metrics['hardware_faithfulness_passed'])
        self.assertFalse(metrics['seam_faithfulness_passed'])
        self.assertEqual(metrics['interior_texture_retention_ratio'], 0.8)
