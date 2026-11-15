"""Explicit reference-aware measurements for instrumented pipeline records.

Default metrics describe downsampled output consistency with the source. They are
not ground-truth reconstruction accuracy. LPIPS is unavailable unless an actual
implementation is added; a gradient distance retains its own name.
"""
import math

import cv2
import numpy as np

from fidelis.eval.benchmark_suite import BenchmarkSuite
from fidelis.eval.detail_metrics import measure_scale_matched_metrics

__all__ = ["measure_pipeline_metrics", "measure_scale_matched_metrics"]


def measure_pipeline_metrics(source_bgr, output_bgr, *, ground_truth_bgr=None,
                             ground_truth_requested=False, bicubic_bgr=None,
                             rois=None, **kwargs):
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

    if bicubic_bgr is not None or rois is not None:
        context['reference'] = 'bicubic_scale_matched'
        context['comparison'] = 'native_scale_matched_to_bicubic'
        if output_bgr.ndim >= 2:
            context['comparison_dimensions'] = [int(output_bgr.shape[1]), int(output_bgr.shape[0])]
        ref_bic_bgr = bicubic_bgr
        if ref_bic_bgr is None and source_bgr is not None and output_bgr.ndim >= 2 and output_bgr.shape[0] > 0 and output_bgr.shape[1] > 0 and source_bgr.ndim == 3 and source_bgr.shape[0] > 0 and source_bgr.shape[1] > 0:
            th, tw = output_bgr.shape[:2]
            if source_bgr.dtype == np.uint8:
                from PIL import Image
                src_rgb = np.ascontiguousarray(source_bgr[:, :, ::-1])
                bic_rgb = np.asarray(Image.fromarray(src_rgb).resize((tw, th), Image.Resampling.BICUBIC), dtype=np.uint8)
                ref_bic_bgr = np.ascontiguousarray(bic_rgb[:, :, ::-1])
            else:
                ref_bic_bgr = cv2.resize(source_bgr.astype(np.float32), (tw, th), interpolation=cv2.INTER_CUBIC)

        sm_kwargs = {
            k: v for k, v in kwargs.items()
            if k in ('roi_space', 'protected', 'master_bgr', 'input_color_order')
        }
        sm = measure_scale_matched_metrics(
            output_bgr,
            ref_bic_bgr,
            source_bgr,
            rois=rois,
            **sm_kwargs,
        )
        context['status'] = sm.get('status', 'unavailable')
        if sm.get('status') == 'measured':
            f2 = sm['interior_texture']
            f3 = sm['oversharpening_restraint']
            f4 = sm['fabric_hardware']
            var_ratio = float(f2['interior_texture_variance_ratio'])
            mid_ratio = float(f2['interior_midband_energy_ratio'])
            fab_reports = f4.get('fabric_reports') or []
            hw_seam_reports = f4.get('hardware_seam_reports') or []
            hw_reports = [r for r in hw_seam_reports if r.get('kind') == 'hardware']
            seam_reports = [r for r in hw_seam_reports if r.get('kind') == 'seam']
            locked_ok = int(f4.get('locked_pixel_mismatches', 0)) == 0

            metrics['interior_texture_retention_ratio'] = round(min(var_ratio, mid_ratio), 6)
            metrics['texture_retention_passed'] = bool(sm['interior_texture_passed'])
            metrics['edge_overshoot'] = float(f3['contour_overshoot_p95'])
            metrics['nyquist_midband_ratio'] = float(f3['contour_nyquist_to_midband_ratio'])
            metrics['halo_restraint_passed'] = bool(sm['oversharpen_restraint_passed'])
            metrics['fabric_weave_coherence'] = (
                float(min(r['weave_orientation_coherence'] for r in fab_reports))
                if fab_reports
                else 1.0
            )
            metrics['fabric_weave_passed'] = bool(sm['fabric_weave_passed'])
            metrics['hardware_faithfulness_passed'] = (
                bool(locked_ok and all(r['passed'] for r in hw_reports))
                if hw_reports
                else bool(locked_ok)
            )
            metrics['seam_faithfulness_passed'] = (
                bool(locked_ok and all(r['passed'] for r in seam_reports))
                if seam_reports
                else bool(locked_ok)
            )
            metrics['all_detail_gates_passed'] = bool(sm['all_detail_gates_passed'])
        else:
            context['reason'] = sm.get('reason', 'scale_matched_unavailable')
            for key in (
                'interior_texture_retention_ratio',
                'texture_retention_passed',
                'edge_overshoot',
                'nyquist_midband_ratio',
                'halo_restraint_passed',
                'fabric_weave_coherence',
                'fabric_weave_passed',
                'hardware_faithfulness_passed',
                'seam_faithfulness_passed',
                'all_detail_gates_passed',
            ):
                metrics[key] = None
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
