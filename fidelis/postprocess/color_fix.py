"""Wavelet and AdaIN Color Stabilization Engine for Fidelis.

Eliminates color shifts, luminance drift, and hue alteration caused by
Variational Autoencoders (VAEs) and iterative diffusion models.
"""

from typing import Optional, Tuple
import numpy as np
from PIL import Image
import scipy.ndimage


def extract_icc_profile(image_path_or_pil) -> Optional[bytes]:
    """Extract and cache the raw ICC color profile from an image."""
    try:
        if isinstance(image_path_or_pil, (str, bytes)):
            with Image.open(image_path_or_pil) as im:
                return im.info.get("icc_profile")
        elif isinstance(image_path_or_pil, Image.Image):
            return image_path_or_pil.info.get("icc_profile")
    except Exception:
        pass
    return None


def wavelet_color_fix(
    sr_img: np.ndarray,
    lq_img: np.ndarray,
    levels: int = 5,
    blend_ratio: float = 1.0
) -> np.ndarray:
    """Stationary Wavelet Color Reconstruction (J=5).

    Extracts high-frequency detail bands H_l from the super-resolved image (SR)
    while substituting the low-frequency color approximation band L_5 from
    the bicubic-upsampled low-quality input (LQ_up).

    Args:
        sr_img: Super-resolved RGB image as float32 in [0, 1] or uint8 [0, 255].
        lq_img: Source LQ image or bicubic upsampled image matching sr_img shape.
        levels: Number of multiscale wavelet decomposition levels (default: 5).
        blend_ratio: Interpolation between raw SR (0.0) and corrected (1.0).

    Returns:
        Color-stabilized RGB image with identical data type to sr_img.
    """
    is_uint8 = sr_img.dtype == np.uint8
    sr_f = sr_img.astype(np.float32) / 255.0 if is_uint8 else sr_img.copy().astype(np.float32)
    lq_f = lq_img.astype(np.float32) / 255.0 if lq_img.dtype == np.uint8 else lq_img.copy().astype(np.float32)

    # Ensure spatial dimensions match exactly via bicubic if needed
    h, w, c = sr_f.shape
    if lq_f.shape[:2] != (h, w):
        pil_lq = Image.fromarray((lq_f * 255.0).clip(0, 255).astype(np.uint8))
        pil_up = pil_lq.resize((w, h), Image.BICUBIC)
        lq_f = np.array(pil_up, dtype=np.float32) / 255.0

    # 5-level stationary decomposition using Gaussian blurring
    # Low-pass residual of SR and LQ_up
    sr_current = sr_f
    sr_high_bands = []

    for l in range(levels):
        sigma = 2 ** l
        # Fast Gaussian low-pass filter
        blurred = np.zeros_like(sr_current)
        for ch in range(c):
            blurred[..., ch] = scipy.ndimage.gaussian_filter(sr_current[..., ch], sigma=sigma)
        high_freq = sr_current - blurred
        sr_high_bands.append(high_freq)
        sr_current = blurred

    # Decompose LQ_up to the deepest low-frequency approximation band
    lq_current = lq_f
    for l in range(levels):
        sigma = 2 ** l
        blurred_lq = np.zeros_like(lq_current)
        for ch in range(c):
            blurred_lq[..., ch] = scipy.ndimage.gaussian_filter(lq_current[..., ch], sigma=sigma)
        lq_current = blurred_lq

    # Reconstruct: combine deepest low-frequency band of LQ_up with high-frequency bands of SR
    reconstructed = lq_current.copy()
    for high_freq in reversed(sr_high_bands):
        reconstructed += high_freq

    reconstructed = np.clip(reconstructed, 0.0, 1.0)
    if blend_ratio < 1.0:
        reconstructed = (1.0 - blend_ratio) * sr_f + blend_ratio * reconstructed

    if is_uint8:
        return (reconstructed * 255.0 + 0.5).clip(0, 255).astype(np.uint8)
    return reconstructed


def adain_color_fix(
    sr_img: np.ndarray,
    lq_img: np.ndarray,
    eps: float = 1e-6,
    blend_ratio: float = 1.0
) -> np.ndarray:
    """Adaptive Instance Normalization (AdaIN) Color Fix.

    Matches channel-wise mean and standard deviation of SR to the reference LQ image.
    Essential for 4x-16x super-resolution to eliminate VAE color cast without bleeding.

    Args:
        sr_img: Super-resolved RGB image.
        lq_img: Source LQ reference image.
        eps: Small epsilon to prevent division by zero.
        blend_ratio: Weight between original SR (0.0) and AdaIN normalized (1.0).

    Returns:
        Color-matched RGB array.
    """
    is_uint8 = sr_img.dtype == np.uint8
    sr_f = sr_img.astype(np.float32) / 255.0 if is_uint8 else sr_img.copy().astype(np.float32)
    lq_f = lq_img.astype(np.float32) / 255.0 if lq_img.dtype == np.uint8 else lq_img.copy().astype(np.float32)

    corrected = np.zeros_like(sr_f)
    for c in range(3):
        mu_lq = np.mean(lq_f[..., c])
        std_lq = np.std(lq_f[..., c])

        mu_sr = np.mean(sr_f[..., c])
        std_sr = np.std(sr_f[..., c])

        # Normalize SR channel and scale to LQ distribution
        norm = (sr_f[..., c] - mu_sr) / (std_sr + eps)
        corrected[..., c] = norm * std_lq + mu_lq

    corrected = np.clip(corrected, 0.0, 1.0)
    if blend_ratio < 1.0:
        corrected = (1.0 - blend_ratio) * sr_f + blend_ratio * corrected

    if is_uint8:
        return (corrected * 255.0 + 0.5).clip(0, 255).astype(np.uint8)
    return corrected


def stabilize_colors(
    sr_img: np.ndarray,
    lq_img: np.ndarray,
    scale_factor: float = 4.0,
    preferred_mode: str = "auto"
) -> np.ndarray:
    """Smart Color Stabilization Entrypoint.

    Automatically routes to Wavelet Color Fix for scale <= 2x and
    AdaIN Color Fix for scale >= 4x as recommended by the research blueprint.
    """
    if preferred_mode == "wavelet" or (preferred_mode == "auto" and scale_factor <= 2.5):
        return wavelet_color_fix(sr_img, lq_img, levels=5)
    elif preferred_mode == "adain" or (preferred_mode == "auto" and scale_factor > 2.5):
        return adain_color_fix(sr_img, lq_img)
    elif preferred_mode == "hybrid":
        # 50/50 blending of Wavelet and AdaIN
        w_fix = wavelet_color_fix(sr_img, lq_img, levels=5)
        a_fix = adain_color_fix(sr_img, lq_img)
        return ((w_fix.astype(np.float32) + a_fix.astype(np.float32)) / 2.0).clip(0, 255).astype(sr_img.dtype)
    return sr_img
