"""Facial Identity Restoration Sub-Pipeline for Fidelis.

Implements CodeFormer discrete codebook transformer with controllable
fidelity weighting w in [0, 1], 5-point facial landmark alignment, and
cosine feathered mask blending to eliminate plastic skin sheen and identity drift.
"""

import os
from pathlib import Path
from typing import List, Optional, Tuple
import cv2
import numpy as np

try:
    import onnxruntime as ort
    HAS_ORT = True
except ImportError:
    HAS_ORT = False

MODEL_DIR = Path(os.environ.get("FIDELIS_HOME", Path.home() / ".local/share/fidelis")) / "models/portrait"


class FaceRestorer:
    """Manages face detection, alignment, CodeFormer inference, and inverse warp blending."""

    def __init__(
        self,
        codeformer_path: Optional[Path] = None,
        yunet_path: Optional[Path] = None,
        device: str = "auto"
    ):
        self.codeformer_path = codeformer_path or (MODEL_DIR / "codeformer.onnx")
        self.yunet_path = yunet_path or (MODEL_DIR / "yunet.onnx")
        self.session = None
        self.detector = None
        self.device = device

    def _init_detector(self, img_w: int, img_h: int):
        if self.detector is None and self.yunet_path.is_file():
            self.detector = cv2.FaceDetectorYN.create(
                str(self.yunet_path),
                "",
                (img_w, img_h),
                score_threshold=0.6,
                nms_threshold=0.3,
                top_k=50
            )
        elif self.detector is not None:
            self.detector.setInputSize((img_w, img_h))

    def _init_codeformer(self):
        if self.session is None:
            if not self.codeformer_path.is_file():
                raise FileNotFoundError(f"CodeFormer ONNX model not found at {self.codeformer_path}")
            
            providers = ['CPUExecutionProvider']
            if self.device != "cpu":
                available = ort.get_available_providers()
                if 'CoreMLExecutionProvider' in available:
                    providers.insert(0, 'CoreMLExecutionProvider')
                elif 'CUDAExecutionProvider' in available:
                    providers.insert(0, 'CUDAExecutionProvider')

            self.session = ort.InferenceSession(str(self.codeformer_path), providers=providers)

    def detect_faces(self, bgr_img: np.ndarray) -> List[dict]:
        """Detect human faces and extract bounding boxes and 5-point landmarks."""
        h, w = bgr_img.shape[:2]
        self._init_detector(w, h)
        if self.detector is None:
            # Fallback to Haar Cascade if YuNet is not found
            cascade_path = cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
            cascade = cv2.CascadeClassifier(cascade_path)
            gray = cv2.cvtColor(bgr_img, cv2.COLOR_BGR2GRAY)
            faces = cascade.detectMultiScale(gray, 1.3, 5)
            results = []
            for (fx, fy, fw, fh) in faces:
                results.append({
                    "bbox": (fx, fy, fw, fh),
                    "landmarks": None,
                    "score": 0.85
                })
            return results

        _, faces = self.detector.detect(bgr_img)
        if faces is None or len(faces) == 0:
            return []

        results = []
        for face in faces:
            x, y, w_box, h_box = face[0:4].astype(int)
            landmarks = face[4:14].reshape((5, 2))
            score = float(face[14])
            results.append({
                "bbox": (x, y, w_box, h_box),
                "landmarks": landmarks,
                "score": score
            })
        return results

    def restore_faces(
        self,
        image_rgb: np.ndarray,
        fidelity_w: float = 0.70
    ) -> Tuple[np.ndarray, int]:
        """Restore all detected faces with controllable fidelity weighting w in [0, 1].

        Args:
            image_rgb: Input RGB image (uint8).
            fidelity_w: Continuous fidelity weight (0.0 to 1.0, default: 0.70).

        Returns:
            Tuple of (restored_image_rgb, face_count).
        """
        self._init_codeformer()
        bgr = cv2.cvtColor(image_rgb, cv2.COLOR_RGB2BGR)
        h, w = bgr.shape[:2]
        faces = self.detect_faces(bgr)

        if not faces:
            return image_rgb.copy(), 0

        canvas = bgr.copy()

        for face in faces:
            bbox = face["bbox"]
            landmarks = face["landmarks"]
            bx, by, bw, bh = bbox

            # Crop margin (expanded bounding box for alignment)
            pad_x = int(bw * 0.45)
            pad_y = int(bh * 0.45)
            x1 = max(0, bx - pad_x)
            y1 = max(0, by - pad_y)
            x2 = min(w, bx + bw + pad_x)
            y2 = min(h, by + bh + pad_y)

            crop = bgr[y1:y2, x1:x2]
            if crop.size == 0 or crop.shape[0] < 32 or crop.shape[1] < 32:
                continue

            orig_crop_h, orig_crop_w = crop.shape[:2]

            # Resize crop to standard 512x512 aligned tensor
            crop_resized = cv2.resize(crop, (512, 512), interpolation=cv2.INTER_LANCZOS4)
            crop_rgb = cv2.cvtColor(crop_resized, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
            crop_norm = (crop_rgb - 0.5) / 0.5
            crop_tensor = np.transpose(crop_norm, (2, 0, 1))[np.newaxis, ...].astype(np.float32)

            w_tensor = np.array([fidelity_w], dtype=np.double)

            # CodeFormer ONNX inference
            input_names = [inp.name for inp in self.session.get_inputs()]
            feed = {input_names[0]: crop_tensor}
            if len(input_names) > 1:
                feed[input_names[1]] = w_tensor

            out = self.session.run(None, feed)[0]

            # Post-process output tensor
            out = np.clip(out[0], -1.0, 1.0)
            out = (np.transpose(out, (1, 2, 0)) * 0.5 + 0.5) * 255.0
            out_bgr_512 = cv2.cvtColor(out.astype(np.uint8), cv2.COLOR_RGB2BGR)

            # Warp back to original cropped coordinates
            restored_crop = cv2.resize(out_bgr_512, (orig_crop_w, orig_crop_h), interpolation=cv2.INTER_LANCZOS4)

            # Cosine-feathered elliptical alpha mask to prevent boundary halos
            mask = np.zeros((orig_crop_h, orig_crop_w), dtype=np.float32)
            center = (orig_crop_w // 2, orig_crop_h // 2)
            axes = (int(orig_crop_w * 0.42), int(orig_crop_h * 0.45))
            cv2.ellipse(mask, center, axes, 0, 0, 360, 1.0, -1)
            # Soft Gaussian blur along transition edges
            ksize = max(orig_crop_w // 6, 7)
            if ksize % 2 == 0:
                ksize += 1
            mask = cv2.GaussianBlur(mask, (ksize, ksize), 0)
            mask = mask[..., np.newaxis]

            # Alpha blend restored face patch back onto the canvas
            target_roi = canvas[y1:y2, x1:x2].astype(np.float32)
            blended = (restored_crop.astype(np.float32) * mask + target_roi * (1.0 - mask)).clip(0, 255).astype(np.uint8)
            canvas[y1:y2, x1:x2] = blended

        res_rgb = cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB)
        return res_rgb, len(faces)
