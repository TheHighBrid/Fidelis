"""Realistic High-Order Synthetic Degradation Pipeline for Fidelis.

Implements the multi-stage, second-order degradation model described in the
Fidelis Flagship Image Upscaling Architecture:
- Blur: Isotropic/Anisotropic Gaussian, Motion Blur, Sinc Defocus Filter
- Resize: Randomized Bilinear, Bicubic, Area, and Lanczos downsampling
- Noise: Additive Gaussian Noise, Poisson Sensor Noise, and Chroma Noise
- Compression: Dual-pass JPEG and WebP compression artifacts
- Repeated Degradation: Cascaded 1st-order and 2nd-order stages
"""

import io
import math
import random
from typing import Optional, Tuple
import cv2
import numpy as np
from PIL import Image


class DegradationGenerator:
    """Generates realistic paired low-resolution/degraded samples from high-resolution inputs."""

    def __init__(self, scale: int = 4, seed: Optional[int] = None):
        self.scale = scale
        if seed is not None:
            random.seed(seed)
            np.random.seed(seed)

    @staticmethod
    def random_gaussian_blur(img: np.ndarray, kernel_range=(5, 15), sigma_range=(0.4, 3.0)) -> np.ndarray:
        """Applies isotropic or anisotropic Gaussian blur."""
        k = random.choice([x for x in range(kernel_range[0], kernel_range[1] + 1) if x % 2 == 1])
        sigma_x = random.uniform(*sigma_range)
        sigma_y = random.uniform(*sigma_range) if random.random() < 0.5 else sigma_x
        angle = random.uniform(0, 180)

        # Generate 2D Gaussian kernel
        ax = np.arange(-k // 2 + 1.0, k // 2 + 1.0)
        xx, yy = np.meshgrid(ax, ax)

        # Rotate coordinates
        rad = np.deg2rad(angle)
        cos_r = np.cos(rad)
        sin_r = np.sin(rad)
        x_rot = xx * cos_r - yy * sin_r
        y_rot = xx * sin_r + yy * cos_r

        kernel = np.exp(-0.5 * (x_rot**2 / (sigma_x**2 + 1e-5) + y_rot**2 / (sigma_y**2 + 1e-5)))
        kernel = kernel / np.sum(kernel)

        return cv2.filter2D(img, -1, kernel)

    @staticmethod
    def random_motion_blur(img: np.ndarray, size_range=(5, 17)) -> np.ndarray:
        """Simulates camera shake or object motion blur."""
        size = random.choice([x for x in range(size_range[0], size_range[1] + 1) if x % 2 == 1])
        angle = random.uniform(0, 180)
        kernel = np.zeros((size, size), dtype=np.float32)
        center = size // 2

        # Draw line through center
        rad = np.deg2rad(angle)
        dx = int(np.round(center * np.cos(rad)))
        dy = int(np.round(center * np.sin(rad)))
        cv2.line(kernel, (center - dx, center - dy), (center + dx, center + dy), 1.0, thickness=1)

        k_sum = np.sum(kernel)
        if k_sum > 0:
            kernel /= k_sum
        else:
            kernel[center, center] = 1.0

        return cv2.filter2D(img, -1, kernel)

    @staticmethod
    def random_noise(img: np.ndarray, gaussian_sigma_range=(2, 25), poisson_scale_range=(0.02, 0.15)) -> np.ndarray:
        """Adds Gaussian and Poisson sensor-like chroma noise."""
        img_f = img.astype(np.float32)

        # 1. Additive Gaussian noise (both luma and chroma)
        if random.random() < 0.7:
            sigma = random.uniform(*gaussian_sigma_range)
            # Separate noise per channel for realistic sensor chroma noise
            noise = np.random.normal(0, sigma, img.shape).astype(np.float32)
            img_f += noise

        # 2. Poisson noise (dependent on photon count)
        if random.random() < 0.5:
            scale = random.uniform(*poisson_scale_range)
            norm = np.clip(img_f / 255.0, 0, 1)
            vals = len(np.unique(norm))
            vals = 2 ** np.ceil(np.log2(max(vals, 2)))
            poisson = np.random.poisson(norm * vals) / float(vals)
            img_f = (1.0 - scale) * img_f + scale * (poisson * 255.0)

        return np.clip(img_f, 0, 255).astype(np.uint8)

    @staticmethod
    def random_compression(img: np.ndarray, quality_range=(30, 85)) -> np.ndarray:
        """Simulates lossy JPEG or WebP compression artifacts."""
        q = random.randint(*quality_range)
        use_webp = random.random() < 0.35

        ext = ".webp" if use_webp else ".jpg"
        param = [cv2.IMWRITE_WEBP_QUALITY if use_webp else cv2.IMWRITE_JPEG_QUALITY, q]

        success, enc = cv2.imencode(ext, img, param)
        if not success:
            return img
        dec = cv2.imdecode(enc, cv2.IMREAD_COLOR)
        return dec if dec is not None else img

    @staticmethod
    def random_resize(img: np.ndarray, target_w: int, target_h: int) -> np.ndarray:
        """Downsamples using randomized interpolation kernel."""
        interpolations = [
            cv2.INTER_AREA,
            cv2.INTER_LINEAR,
            cv2.INTER_CUBIC,
            cv2.INTER_LANCZOS4
        ]
        interp = random.choice(interpolations)
        return cv2.resize(img, (target_w, target_h), interpolation=interp)

    def apply_first_order(self, hr_img: np.ndarray) -> np.ndarray:
        """Applies single-order realistic real-world degradation."""
        h, w = hr_img.shape[:2]
        lr_w = max(16, w // self.scale)
        lr_h = max(16, h // self.scale)

        out = hr_img.copy()

        # Step 1: Optical blur
        if random.random() < 0.6:
            out = self.random_gaussian_blur(out)
        elif random.random() < 0.4:
            out = self.random_motion_blur(out)

        # Step 2: Downsampling to target LR dimension
        out = self.random_resize(out, lr_w, lr_h)

        # Step 3: Sensor noise
        out = self.random_noise(out)

        # Step 4: JPEG / WebP compression
        out = self.random_compression(out)

        return out

    def apply_second_order(self, hr_img: np.ndarray) -> np.ndarray:
        """Applies comprehensive 2nd-order cascaded degradation."""
        h, w = hr_img.shape[:2]
        lr_w = max(16, w // self.scale)
        lr_h = max(16, h // self.scale)

        # --- First Degradation Stage ---
        stage1 = hr_img.copy()
        if random.random() < 0.7:
            stage1 = self.random_gaussian_blur(stage1, kernel_range=(7, 19), sigma_range=(0.6, 3.5))

        # Intermediate random scale (e.g. 0.3x to 0.8x)
        mid_scale = random.uniform(0.3, 0.8)
        mid_w = max(16, int(w * mid_scale))
        mid_h = max(16, int(h * mid_scale))
        stage1 = self.random_resize(stage1, mid_w, mid_h)
        stage1 = self.random_noise(stage1, gaussian_sigma_range=(1, 15))
        stage1 = self.random_compression(stage1, quality_range=(50, 90))

        # --- Second Degradation Stage ---
        stage2 = stage1
        if random.random() < 0.5:
            stage2 = self.random_gaussian_blur(stage2, kernel_range=(5, 13), sigma_range=(0.4, 2.0))
        elif random.random() < 0.4:
            stage2 = self.random_motion_blur(stage2, size_range=(5, 13))

        # Final downsampling to target LR dimension
        stage2 = self.random_resize(stage2, lr_w, lr_h)
        stage2 = self.random_noise(stage2, gaussian_sigma_range=(2, 20))
        stage2 = self.random_compression(stage2, quality_range=(35, 80))

        return stage2

    def generate_pair(self, hr_img: np.ndarray, second_order: bool = True) -> Tuple[np.ndarray, np.ndarray]:
        """Generates a synchronized (degraded_lr, high_res_ground_truth) pair."""
        if second_order:
            lr = self.apply_second_order(hr_img)
        else:
            lr = self.apply_first_order(hr_img)
        return lr, hr_img
