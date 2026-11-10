"""Explicit reference-aware measurements for instrumented pipeline records.

Default metrics describe downsampled output consistency with the source. They are
not ground-truth reconstruction accuracy. LPIPS is unavailable unless an actual
implementation is added; a gradient distance retains its own name.
"""
import math

import cv2
import numpy as np

from fidelis.eval.benchmark_suite import BenchmarkSuite


def measure_pipeline_metrics(source_bgr, output_bgr, *, ground_truth_bgr=None,
                             ground_truth_requested=False):
    metrics = {name: None for name in ('psnr', 'ssim', 'lpips', 'lpips_proxy',
                                       'cielab_delta_e', 'gradient_coherence_pct',
                                       'gradient_distance_proxy')}
    context = {
        'schema_version': 2,
        'status': 'unavailable',
        'reference': 'paired_ground_truth' if ground_truth_requested else 'source_consistency',
        'comparison': 'native_output_to_ground_truth' if ground_truth_requested else 'output_area_downsampled_to_source',
        'lpips_status': 'not_computed',
        'lpips_proxy_status': 'not_computed',
        'gradient_distance_method': 'one_minus_gradient_coherence_fraction',
        'delta_e_method': 'CIE76_float_Lab',
    }
    if output_bgr is None:
        context['reason'] = 'output_decode_unavailable'
        return metrics, context
    if ground_truth_requested:
        if ground_truth_bgr is None:
            context['reason'] = 'ground_truth_decode_unavailable'
            return metrics, context
        if output_bgr.shape != ground_truth_bgr.shape:
            context['reason'] = 'ground_truth_dimensions_mismatch'
            return metrics, context
        reference, candidate = ground_truth_bgr, output_bgr
    else:
        if source_bgr is None:
            context['reason'] = 'source_decode_unavailable'
            return metrics, context
        reference = source_bgr
        candidate = cv2.resize(output_bgr, (reference.shape[1], reference.shape[0]), interpolation=cv2.INTER_AREA)
    try:
        reference = cv2.cvtColor(reference, cv2.COLOR_BGR2RGB)
        candidate = cv2.cvtColor(candidate, cv2.COLOR_BGR2RGB)
        context['comparison_dimensions'] = [reference.shape[1], reference.shape[0]]
        measured = {
            'psnr': BenchmarkSuite.compute_psnr(candidate, reference),
            'ssim': BenchmarkSuite.compute_ssim(candidate, reference),
            'cielab_delta_e': BenchmarkSuite.compute_cielab_delta_e(candidate, reference),
            'gradient_coherence_pct': BenchmarkSuite.compute_gradient_coherence(candidate, reference),
        }
        for name, value in measured.items():
            if math.isfinite(value):
                metrics[name] = round(float(value), 6)
        if metrics['gradient_coherence_pct'] is not None:
            metrics['gradient_distance_proxy'] = round(max(0., min(1., 1.-metrics['gradient_coherence_pct']/100.)), 6)
        available = [name for name in measured if metrics[name] is not None]
        context['status'] = 'measured' if len(available) == len(measured) else ('partial' if available else 'unavailable')
        if len(available) != len(measured):
            context['reason'] = 'nonfinite_measurement'
    except (cv2.error, ValueError, TypeError, FloatingPointError) as error:
        context.update(reason='measurement_failed', error_type=type(error).__name__)
    return metrics, context
