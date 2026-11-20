"""Fidelis Core Pipeline and Routing Components."""
from __future__ import annotations

from fidelis.core.pipeline import (
    PipelineExecutionResult,
    TelemetrySpan,
    UpscalePipeline,
)
from fidelis.core.router import (
    DegradationProfile,
    DegradationProfiler,
    SmartRouter,
    UpscaleMode,
)

__all__ = [
    "DegradationProfile",
    "DegradationProfiler",
    "PipelineExecutionResult",
    "SmartRouter",
    "TelemetrySpan",
    "UpscaleMode",
    "UpscalePipeline",
]
