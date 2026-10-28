"""Fidelis: Flagship Multi-Stage Photographic Image Restoration & Super-Resolution Suite."""

__version__ = "3.2.0"

from fidelis.core.router import SmartRouter, DegradationProfiler, UpscaleMode
from fidelis.engine.tiler import MultiDiffusionTiler
from fidelis.engine.diffusion_sr import DiffusionPresetsEngine
from fidelis.modules.face_restorer import FaceRestorer
from fidelis.modules.text_restorer import TextRestorer
from fidelis.postprocess.color_fix import stabilize_colors, wavelet_color_fix, adain_color_fix
from fidelis.eval.benchmark_suite import BenchmarkSuite

__all__ = [
    "SmartRouter",
    "DegradationProfiler",
    "UpscaleMode",
    "MultiDiffusionTiler",
    "DiffusionPresetsEngine",
    "FaceRestorer",
    "TextRestorer",
    "stabilize_colors",
    "wavelet_color_fix",
    "adain_color_fix",
    "BenchmarkSuite",
]
