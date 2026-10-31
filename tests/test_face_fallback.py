"""The profiler must tolerate OpenCV builds without the optional Haar detector."""

import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

import numpy as np

path = Path(__file__).resolve().parents[1] / "fidelis/modules/face_restorer.py"
spec = importlib.util.spec_from_file_location("face_restorer_under_test", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class OptionalFaceDetectorTests(unittest.TestCase):
    def test_missing_haar_classifier_returns_no_faces_without_crashing(self):
        restorer = module.FaceRestorer(
            yunet_path=Path("/nonexistent/fidelis-yunet.onnx")
        )
        image = np.zeros((64, 64, 3), dtype=np.uint8)
        with patch.object(module.cv2, "CascadeClassifier", None, create=True):
            self.assertEqual(restorer.detect_faces(image), [])

    def test_missing_haar_data_returns_no_faces_without_crashing(self):
        restorer = module.FaceRestorer(
            yunet_path=Path("/nonexistent/fidelis-yunet.onnx")
        )
        image = np.zeros((64, 64, 3), dtype=np.uint8)
        with patch.object(module.cv2, "data", None, create=True):
            self.assertEqual(restorer.detect_faces(image), [])


if __name__ == "__main__":
    unittest.main()
