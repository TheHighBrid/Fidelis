"""Text-First Glyph Restoration Sub-Pipeline for Fidelis.

Implements text region detection, strict empty-text guard clauses,
and high-frequency glyph stroke reconstruction for logos, UI, and scene text.
"""

from typing import List, Tuple
import cv2
import numpy as np


class TextRestorer:
    """Detects and sharpens typography and brand logos to prevent melted character strokes."""

    def __init__(self, confidence_thresh: float = 0.5):
        self.confidence_thresh = confidence_thresh

    def detect_text_regions(self, gray: np.ndarray) -> List[Tuple[int, int, int, int]]:
        """Detect text bounding boxes using morphological stroke energy and MSER.

        Returns list of bounding boxes (x, y, w, h).
        """
        # Sobel edge gradient in horizontal direction (text lines have dense vertical strokes)
        grad_x = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
        grad_y = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
        grad_mag = cv2.magnitude(grad_x, grad_y)
        grad_norm = cv2.normalize(grad_mag, None, 0, 255, cv2.NORM_MINMAX, dtype=cv2.CV_8U)

        # Morphological closing to bridge adjacent letters into word blocks
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 3))
        connected = cv2.morphologyEx(grad_norm, cv2.MORPH_CLOSE, kernel)

        _, thresh = cv2.threshold(connected, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        h, w = gray.shape[:2]
        min_area = (h * w) * 0.0002
        max_area = (h * w) * 0.25

        boxes = []
        for c in contours:
            area = cv2.contourArea(c)
            if min_area < area < max_area:
                bx, by, bw, bh = cv2.boundingRect(c)
                aspect = bw / float(bh)
                # Text usually has aspect ratio >= 1.0 or moderate vertical ratio
                if 0.5 <= aspect <= 20.0 and bh >= 10:
                    boxes.append((bx, by, bw, bh))

        return boxes

    def restore_text(
        self,
        image_rgb: np.ndarray,
        sharpening_strength: float = 0.65
    ) -> Tuple[np.ndarray, int]:
        """Sharpen glyph strokes across detected text regions.

        Strict guard clause: if zero text regions are detected, returns original
        image immediately without processing.

        Args:
            image_rgb: Input RGB image (uint8).
            sharpening_strength: Stroke enhancement strength (0.0 to 1.0).

        Returns:
            Tuple of (restored_image_rgb, text_region_count).
        """
        gray = cv2.cvtColor(image_rgb, cv2.COLOR_RGB2GRAY)
        boxes = self.detect_text_regions(gray)

        # Strict empty-text guard clause
        if not boxes:
            return image_rgb.copy(), 0

        canvas = image_rgb.copy()

        for (bx, by, bw, bh) in boxes:
            # Add small padding around text block
            pad = int(min(bw, bh) * 0.15)
            x1 = max(0, bx - pad)
            y1 = max(0, by - pad)
            x2 = min(image_rgb.shape[1], bx + bw + pad)
            y2 = min(image_rgb.shape[0], by + bh + pad)

            crop = canvas[y1:y2, x1:x2].astype(np.float32)
            if crop.size == 0:
                continue

            # Unsharp masking and directional gradient boost for crisp glyph edges
            blurred = cv2.GaussianBlur(crop, (0, 0), sigmaX=1.2)
            high_freq = crop - blurred
            enhanced = crop + sharpening_strength * high_freq

            # Cosine-feathered border to blend seamlessly
            ch, cw = crop.shape[:2]
            mask = np.ones((ch, cw), dtype=np.float32)
            margin = max(min(ch, cw) // 6, 2)
            for i in range(margin):
                factor = 0.5 * (1.0 - np.cos(np.pi * (i + 1) / margin))
                mask[i, :] = np.minimum(mask[i, :], factor)
                mask[ch - 1 - i, :] = np.minimum(mask[ch - 1 - i, :], factor)
                mask[:, i] = np.minimum(mask[:, i], factor)
                mask[:, cw - 1 - i] = np.minimum(mask[:, cw - 1 - i], factor)

            mask = mask[..., np.newaxis]
            canvas[y1:y2, x1:x2] = (enhanced * mask + crop * (1.0 - mask)).clip(0, 255).astype(np.uint8)

        return canvas, len(boxes)
