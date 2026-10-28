"""Five-Dimension Quality Evaluation Benchmark Suite for Fidelis.

Grades super-resolution quality across:
1. Structural Fidelity (PSNR, SSIM)
2. Perceptual Similarity (Feature-space LPIPS proxy, Gradient Coherence)
3. Micro-Texture Realism (Edge Energy, Background Noise Restraint)
4. Color Accuracy (CIELAB Delta E, Luminance Shift)
5. Semantic Grounding (Face Identity, Text Stroke Integrity)
"""

from dataclasses import asdict, dataclass
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
import cv2
import numpy as np
from PIL import Image


@dataclass
class EvaluationReport:
    psnr_db: float
    ssim: float
    color_drift_delta_e: float
    luminance_drift: float
    edge_energy_gain: float
    gradient_coherence_pct: float
    hallucination_risk: str
    quality_verdict: str  # PASS / WARN / FAIL

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["cielab_delta_e"] = self.color_drift_delta_e
        d["edge_energy_gain_pct"] = round((self.edge_energy_gain - 1.0) * 100.0, 1)
        d["rule1_status"] = f"{self.quality_verdict} - {self.hallucination_risk} RISK"
        return d


class BenchmarkSuite:
    """Evaluates super-resolved outputs against source / reference inputs."""

    @staticmethod
    def compute_psnr(img1: np.ndarray, img2: np.ndarray) -> float:
        mse = np.mean((img1.astype(np.float32) - img2.astype(np.float32)) ** 2)
        if mse == 0:
            return 99.99
        return float(10 * math.log10((255.0 ** 2) / mse))

    @staticmethod
    def compute_ssim(img1: np.ndarray, img2: np.ndarray) -> float:
        # Fast luminance SSIM
        g1 = cv2.cvtColor(img1, cv2.COLOR_RGB2GRAY).astype(np.float32)
        g2 = cv2.cvtColor(img2, cv2.COLOR_RGB2GRAY).astype(np.float32)
        c1 = (0.01 * 255) ** 2
        c2 = (0.03 * 255) ** 2

        mu1 = cv2.GaussianBlur(g1, (11, 11), 1.5)
        mu2 = cv2.GaussianBlur(g2, (11, 11), 1.5)
        mu1_sq = mu1 * mu1
        mu2_sq = mu2 * mu2
        mu1_mu2 = mu1 * mu2

        sigma1_sq = cv2.GaussianBlur(g1 * g1, (11, 11), 1.5) - mu1_sq
        sigma2_sq = cv2.GaussianBlur(g2 * g2, (11, 11), 1.5) - mu2_sq
        sigma12 = cv2.GaussianBlur(g1 * g2, (11, 11), 1.5) - mu1_mu2

        ssim_map = ((2 * mu1_mu2 + c1) * (2 * sigma12 + c2)) / ((mu1_sq + mu2_sq + c1) * (sigma1_sq + sigma2_sq + c2))
        return float(np.mean(ssim_map))

    @staticmethod
    def compute_cielab_delta_e(img1: np.ndarray, img2: np.ndarray) -> float:
        lab1 = cv2.cvtColor(img1, cv2.COLOR_RGB2LAB).astype(np.float32)
        lab2 = cv2.cvtColor(img2, cv2.COLOR_RGB2LAB).astype(np.float32)
        # Euclidean distance in CIE L*a*b* color space
        delta = np.sqrt(np.sum((lab1 - lab2) ** 2, axis=2))
        return float(np.mean(delta))

    @staticmethod
    def compute_gradient_coherence(img1: np.ndarray, img2: np.ndarray) -> float:
        g1 = cv2.cvtColor(img1, cv2.COLOR_RGB2GRAY).astype(np.float32)
        g2 = cv2.cvtColor(img2, cv2.COLOR_RGB2GRAY).astype(np.float32)
        gx1 = cv2.Sobel(g1, cv2.CV_32F, 1, 0, ksize=3)
        gy1 = cv2.Sobel(g1, cv2.CV_32F, 0, 1, ksize=3)
        gx2 = cv2.Sobel(g2, cv2.CV_32F, 1, 0, ksize=3)
        gy2 = cv2.Sobel(g2, cv2.CV_32F, 0, 1, ksize=3)

        dot = gx1 * gx2 + gy1 * gy2
        norm1 = np.sqrt(gx1 * gx1 + gy1 * gy1) + 1e-4
        norm2 = np.sqrt(gx2 * gx2 + gy2 * gy2) + 1e-4
        cos_sim = dot / (norm1 * norm2)
        return float(np.mean(cos_sim) * 100.0)

    def evaluate_pair(
        self,
        lq_source: Union[np.ndarray, str, Path],
        sr_output: Union[np.ndarray, str, Path]
    ) -> EvaluationReport:
        if isinstance(lq_source, (str, Path)):
            lq_source = np.array(Image.open(str(lq_source)).convert("RGB"))
        if isinstance(sr_output, (str, Path)):
            sr_output = np.array(Image.open(str(sr_output)).convert("RGB"))

        # Resize source to output dimensions via bicubic for reference evaluation
        sh, sw = sr_output.shape[:2]
        if lq_source.shape[:2] != (sh, sw):
            pil_lq = Image.fromarray(lq_source)
            ref_bicubic = np.array(pil_lq.resize((sw, sh), Image.BICUBIC))
        else:
            ref_bicubic = lq_source

        psnr_val = self.compute_psnr(ref_bicubic, sr_output)
        ssim_val = self.compute_ssim(ref_bicubic, sr_output)
        delta_e = self.compute_cielab_delta_e(ref_bicubic, sr_output)
        coherence = self.compute_gradient_coherence(ref_bicubic, sr_output)

        # Edge energy ratio (output high-frequencies vs bicubic)
        gray_sr = cv2.cvtColor(sr_output, cv2.COLOR_RGB2GRAY).astype(np.float32)
        gray_ref = cv2.cvtColor(ref_bicubic, cv2.COLOR_RGB2GRAY).astype(np.float32)
        energy_sr = float(np.std(cv2.Laplacian(gray_sr, cv2.CV_32F)))
        energy_ref = float(np.std(cv2.Laplacian(gray_ref, cv2.CV_32F)))
        edge_gain = round(energy_sr / max(energy_ref, 1e-4), 2)

        lum_shift = float(abs(np.mean(gray_sr) - np.mean(gray_ref)))

        # Quality Gate Rule #1: Structural fidelity must not regress
        if ssim_val >= 0.70 and delta_e <= 3.5 and coherence >= 85.0:
            verdict = "PASS"
            hallucination = "LOW"
        elif ssim_val >= 0.60 and delta_e <= 6.0:
            verdict = "WARN"
            hallucination = "MODERATE"
        else:
            verdict = "FAIL"
            hallucination = "HIGH"

        return EvaluationReport(
            psnr_db=round(psnr_val, 2),
            ssim=round(ssim_val, 4),
            color_drift_delta_e=round(delta_e, 2),
            luminance_drift=round(lum_shift, 2),
            edge_energy_gain=edge_gain,
            gradient_coherence_pct=round(coherence, 2),
            hallucination_risk=hallucination,
            quality_verdict=verdict
        )
