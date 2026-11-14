"""Fidelis: Flagship Multi-Stage Photographic Image Restoration & Super-Resolution Suite."""

import importlib

__version__ = "3.2.0"

_LAZY_IMPORTS = {
    "SmartRouter": ("fidelis.core.router", "SmartRouter"),
    "DegradationProfiler": ("fidelis.core.router", "DegradationProfiler"),
    "UpscaleMode": ("fidelis.core.router", "UpscaleMode"),
    "MultiDiffusionTiler": ("fidelis.engine.tiler", "MultiDiffusionTiler"),
    "DiffusionPresetsEngine": ("fidelis.engine.diffusion_sr", "DiffusionPresetsEngine"),
    "FaceRestorer": ("fidelis.modules.face_restorer", "FaceRestorer"),
    "TextRestorer": ("fidelis.modules.text_restorer", "TextRestorer"),
    "stabilize_colors": ("fidelis.postprocess.color_fix", "stabilize_colors"),
    "wavelet_color_fix": ("fidelis.postprocess.color_fix", "wavelet_color_fix"),
    "adain_color_fix": ("fidelis.postprocess.color_fix", "adain_color_fix"),
    "BenchmarkSuite": ("fidelis.eval.benchmark_suite", "BenchmarkSuite"),
    "EvaluationCorpus": ("fidelis.eval.corpus", "EvaluationCorpus"),
    "TestBucket": ("fidelis.eval.corpus", "TestBucket"),
    "DegradationGenerator": ("fidelis.data.degradation", "DegradationGenerator"),
    "SelfImprovementEngine": ("fidelis.tune.optimizer", "SelfImprovementEngine"),
}

__all__ = list(_LAZY_IMPORTS.keys())


def __getattr__(name: str):
    target = _LAZY_IMPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr_name = target
    module = importlib.import_module(module_name)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value
