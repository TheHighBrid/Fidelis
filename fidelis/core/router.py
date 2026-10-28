"""Model Registry and Smart Degradation Router for Fidelis.

Performs mathematical pre-flight profiling on incoming images:
- Noise variance via median absolute deviation (MAD) of wavelet detail
- Blur severity via variance of the spatial Laplacian
- 8x8 boundary gradients for JPEG compression blockiness
- Semantic ROI detection (Faces & Scene Typography)

Routes execution dynamically across:
1. Faithful Tier (RAESR / Real-HAT-GAN / Real-ESRGAN)
2. Balanced Tier (1-Step Distilled Diffusion / OSEDiff / PiSA-SR)
3. Creative / Photo Restore Tier (MultiDiffusion / SUPIR)
"""

from dataclasses import dataclass
from enum import Enum
import math
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import cv2
import numpy as np
from PIL import Image

from fidelis.modules.face_restorer import FaceRestorer
from fidelis.modules.text_restorer import TextRestorer


class UpscaleMode(str, Enum):
    AUTO = "auto"
    FAITHFUL = "faithful"
    BALANCED = "balanced"
    CREATIVE = "creative"
    PHOTO_RESTORE = "photo_restore"


@dataclass
class DegradationProfile:
    width: int
    height: int
    blur_score: float       # Laplacian variance (lower = blurrier)
    noise_variance: float   # Wavelet MAD noise estimate (higher = noisier)
    jpeg_blockiness: float  # 8x8 DCT grid artifact intensity
    face_count: int
    text_count: int
    has_faces: bool
    has_text: bool
    is_clean_high_res: bool
    recommended_mode: str
    recommended_model: str


class DegradationProfiler:
    """Computes mathematical degradation metrics without heavy neural models (<15ms)."""

    def __init__(self):
        self.face_detector = FaceRestorer()
        self.text_detector = TextRestorer()

    def profile(self, image_rgb: np.ndarray) -> DegradationProfile:
        h, w = image_rgb.shape[:2]
        gray = cv2.cvtColor(image_rgb, cv2.COLOR_RGB2GRAY)

        # 1. Blur estimation via Variance of Laplacian
        laplacian = cv2.Laplacian(gray, cv2.CV_32F)
        blur_score = float(np.var(laplacian))

        # 2. Noise variance via Median Absolute Deviation (MAD) of high-frequency sub-band
        down = cv2.pyrDown(gray)
        up = cv2.pyrUp(down, dstsize=(w, h))
        high_freq = np.abs(gray.astype(np.float32) - up.astype(np.float32))
        mad = float(np.median(high_freq))
        noise_variance = float((mad / 0.6745) ** 2)

        # 3. 8x8 JPEG Blockiness boundary gradient
        # Measures gradient spike specifically at 8-pixel intervals vs off-grid pixels
        diff_x = np.abs(np.diff(gray.astype(np.float32), axis=1))
        if diff_x.shape[1] >= 16:
            grid_cols = diff_x[:, 7::8]
            non_grid_cols = diff_x[:, 3::8]
            grid_mean = np.mean(grid_cols) if grid_cols.size > 0 else 0.0
            non_grid_mean = np.mean(non_grid_cols) if non_grid_cols.size > 0 else 1.0
            blockiness = float(grid_mean / (non_grid_mean + 1e-4))
        else:
            blockiness = 1.0

        # 4. Face and Text detection
        bgr = cv2.cvtColor(image_rgb, cv2.COLOR_RGB2BGR)
        faces = self.face_detector.detect_faces(bgr)
        text_boxes = self.text_detector.detect_text_regions(gray)

        face_count = len(faces)
        text_count = len(text_boxes)
        has_faces = face_count > 0
        has_text = text_count > 0

        is_clean_high_res = (w >= 1024 or h >= 1024) and blur_score > 250.0 and noise_variance < 15.0

        # Smart routing decision logic
        if has_text and text_count >= 2:
            # Text and identity-sensitive images default toward fidelity
            recommended_mode = "faithful"
            recommended_model = "Real-HAT-GAN"
        elif has_faces:
            recommended_mode = "balanced"
            recommended_model = "Smart_Balanced"
        elif is_clean_high_res:
            recommended_mode = "faithful"
            recommended_model = "RAESR"
        elif blur_score < 75.0 or noise_variance > 50.0 or blockiness > 1.3:
            recommended_mode = "photo_restore"
            recommended_model = "Photo_Restore"
        else:
            recommended_mode = "balanced"
            recommended_model = "Smart_Balanced"

        return DegradationProfile(
            width=w,
            height=h,
            blur_score=round(blur_score, 2),
            noise_variance=round(noise_variance, 2),
            jpeg_blockiness=round(blockiness, 3),
            face_count=face_count,
            text_count=text_count,
            has_faces=has_faces,
            has_text=has_text,
            is_clean_high_res=is_clean_high_res,
            recommended_mode=recommended_mode,
            recommended_model=recommended_model
        )


class SmartRouter:
    """Orchestrates model selection based on user mode and image degradation profile."""

    def __init__(self):
        self.profiler = DegradationProfiler()

    def route(
        self,
        image_rgb: np.ndarray,
        requested_mode: UpscaleMode = UpscaleMode.AUTO,
        preserve_text: bool = True
    ) -> Dict:
        profile = self.profiler.profile(image_rgb)

        if requested_mode == UpscaleMode.AUTO:
            active_mode = profile.recommended_mode
        else:
            active_mode = requested_mode.value

        # Select execution configuration
        if active_mode == "faithful":
            model = "Real-HAT-GAN" if profile.has_text else "RAESR"
            tier = 1
        elif active_mode == "balanced":
            model = "Smart_Balanced"
            tier = 2
        elif active_mode == "creative":
            model = "Ultra_Redefine"
            tier = 3
        else:
            model = "Photo_Restore"
            tier = 3

        return {
            "mode": active_mode,
            "tier": tier,
            "model": model,
            "profile": profile,
            "actions": {
                "run_face_restoration": profile.has_faces,
                "face_count": profile.face_count,
                "face_fidelity_w": 0.70 if profile.blur_score > 80 else 0.50,
                "run_text_restoration": profile.has_text and preserve_text,
                "text_count": profile.text_count,
                "color_correction": "wavelet" if profile.width <= 1024 else "adain"
            }
        }
