"""Unit tests for fidelis.engine.restoration_runner (F7)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

from fidelis.engine import (
    BackendUnavailableError,
    BicubicBaselineBackend,
    ComfyRestorationBackend,
    DimensionMismatchError,
    ImportedRestorationBackend,
    OnnxRestorationBackend,
    RestorationRunner,
    TorchSpandrelRestorationBackend,
    create_restoration_runner,
)
from fidelis.eval.comparators import run_comparators


def _make_textured_rgb(h: int = 16, w: int = 16, seed: int = 7) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.integers(30, 225, size=(h, w, 3), dtype=np.uint8)


class RestorationRunnerTests(unittest.TestCase):
    def test_bicubic_baseline_and_provenance(self) -> None:
        src = _make_textured_rgb(16, 16)
        runner = create_restoration_runner("bicubic")
        res = runner.run(src, scale=4, apply_texture_guard=False)
        self.assertEqual(res.image.shape, (64, 64, 3))
        self.assertEqual(res.image.dtype, np.uint8)
        self.assertEqual(res.provenance.backend, "bicubic")
        self.assertEqual(res.provenance.weights_sha256, "deterministic_bicubic")
        self.assertEqual(res.provenance.source_shape, (16, 16, 3))
        self.assertEqual(res.provenance.target_shape, (64, 64, 3))
        self.assertFalse(res.provenance.texture_guard_applied)
        self.assertIsNone(res.guard_receipt)
        self.assertIsNone(res.drift_report)
        d = res.provenance.to_dict()
        self.assertEqual(d["target_shape"], [64, 64, 3])

    def test_imported_backend_exact_grid_and_dimension_mismatch(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = _make_textured_rgb(16, 16)
            good_4x = _make_textured_rgb(64, 64, seed=11)
            bad_4x = _make_textured_rgb(60, 64, seed=12)
            Image.fromarray(good_4x).save(root / "case_ok.png")
            Image.fromarray(bad_4x).save(root / "case_bad.png")

            runner = create_restoration_runner("imported", imported_dir=root)
            res = runner.run(src, scale=4, case_id="case_ok", apply_texture_guard=False)
            np.testing.assert_array_equal(res.image, good_4x)
            self.assertEqual(res.provenance.backend, "imported")
            self.assertEqual(res.provenance.weights_sha256, "imported")

            with self.assertRaises(DimensionMismatchError):
                runner.run(src, scale=4, case_id="case_bad", apply_texture_guard=False)

    def test_comfy_backend_passes_4x_bicubic_canvas_and_enforces_shape(self) -> None:
        src = _make_textured_rgb(16, 16)
        bundle = {"schema_version": 1, "family": "sdxl", "workflow": {}}

        class _FakeComfy:
            address = "http://127.0.0.1:8188"
            seen_shape = None

            def default_cli_run_id(self, canvas, b, addr):
                return "run-123"

            def run(self, canvas, b, *, run_id=None, deadline_seconds=300):
                self.seen_shape = canvas.shape
                out = np.clip(canvas.astype(np.int16) + 5, 0, 255).astype(np.uint8)
                return out, {"id": run_id, "workflow_sha256": "wf_abc", "family": "sdxl"}

        fake = _FakeComfy()
        runner = create_restoration_runner("comfyui", bundle=bundle, comfy_backend=fake)
        res = runner.run(src, scale=4, apply_texture_guard=False)
        self.assertEqual(fake.seen_shape, (64, 64, 3))
        self.assertEqual(res.image.shape, (64, 64, 3))
        self.assertEqual(res.provenance.backend, "comfyui")
        self.assertEqual(res.provenance.extra["workflow_sha256"], "wf_abc")

        class _BadShapeComfy(_FakeComfy):
            def run(self, canvas, b, *, run_id=None, deadline_seconds=300):
                return np.zeros((32, 32, 3), dtype=np.uint8), {"id": run_id}

        bad_runner = RestorationRunner(
            ComfyRestorationBackend(bundle=bundle, comfy_backend=_BadShapeComfy())
        )
        with self.assertRaises(DimensionMismatchError):
            bad_runner.run(src, scale=4, apply_texture_guard=False)

    def test_onnx_backend_unavailable_and_mocked_session(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            weights = Path(tmp) / "model.onnx"
            weights.write_bytes(b"fake-onnx-weights")
            expected_sha = hashlib.sha256(b"fake-onnx-weights").hexdigest()

            with self.assertRaises(BackendUnavailableError):
                create_restoration_runner("onnxruntime", weights_path=weights)

            class _FakeInput:
                name = "input"

            class _FakeSession:
                def __init__(self, out_shape):
                    self._out_shape = out_shape

                def get_inputs(self):
                    return [_FakeInput()]

                def run(self, output_names, feeds):
                    return [np.full(self._out_shape, 0.5, dtype=np.float32)]

            fake_ort = types.SimpleNamespace(
                InferenceSession=lambda path, providers=None: _FakeSession((1, 3, 64, 64))
            )
            with patch.dict(sys.modules, {"onnxruntime": fake_ort}):
                runner = create_restoration_runner("onnxruntime", weights_path=weights)
                res = runner.run(_make_textured_rgb(16, 16), scale=4, apply_texture_guard=False)
                self.assertEqual(res.image.shape, (64, 64, 3))
                self.assertEqual(res.provenance.weights_sha256, expected_sha)

            bad_backend = OnnxRestorationBackend(
                weights, session=_FakeSession((1, 3, 32, 32))
            )
            with self.assertRaises(DimensionMismatchError):
                RestorationRunner(bad_backend).run(_make_textured_rgb(16, 16), scale=4)

    def test_torch_spandrel_unavailable_and_mocked(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            weights = Path(tmp) / "model.pth"
            weights.write_bytes(b"fake-pth-weights")
            expected_sha = hashlib.sha256(b"fake-pth-weights").hexdigest()

            with self.assertRaises(BackendUnavailableError):
                create_restoration_runner("torch_spandrel", weights_path=weights)

            class _FakeTensor:
                def __init__(self, arr: np.ndarray):
                    self.arr = arr

                def permute(self, *dims):
                    return _FakeTensor(self.arr.transpose(dims))

                def unsqueeze(self, dim):
                    return _FakeTensor(np.expand_dims(self.arr, axis=dim))

                def squeeze(self, dim):
                    return _FakeTensor(np.squeeze(self.arr, axis=dim))

                def to(self, device):
                    return self

                def detach(self):
                    return self

                def cpu(self):
                    return self

                def numpy(self):
                    return self.arr

            class _NoGrad:
                def __enter__(self):
                    return None

                def __exit__(self, *args):
                    return False

            fake_torch = types.SimpleNamespace(
                from_numpy=lambda arr: _FakeTensor(arr),
                no_grad=lambda: _NoGrad(),
            )

            class _FakeModel:
                def to(self, device):
                    return self

                def eval(self):
                    return self

                def __call__(self, inp):
                    _, c, h, w = inp.arr.shape
                    return _FakeTensor(np.full((1, c, h * 4, w * 4), 0.25, dtype=np.float32))

            fake_spandrel = types.SimpleNamespace(
                ModelLoader=lambda: types.SimpleNamespace(
                    load_from_file=lambda p: types.SimpleNamespace(model=_FakeModel())
                )
            )
            with patch.dict(sys.modules, {"torch": fake_torch, "spandrel": fake_spandrel}):
                runner = create_restoration_runner("torch_spandrel", weights_path=weights)
                res = runner.run(_make_textured_rgb(16, 16), scale=4, apply_texture_guard=False)
                self.assertEqual(res.image.shape, (64, 64, 3))
                self.assertEqual(res.provenance.weights_sha256, expected_sha)

    def test_texture_guard_locks_preserve_roi_and_blends_interior_texture(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = _make_textured_rgb(16, 16, seed=3)
            base_4x = np.asarray(
                Image.fromarray(src).resize((64, 64), Image.Resampling.BICUBIC),
                dtype=np.uint8,
            )
            # Candidate differs strongly everywhere
            cand_4x = np.clip(255 - base_4x, 0, 255).astype(np.uint8)
            Image.fromarray(cand_4x).save(root / "sample.png")

            rois = [
                {"id": "hw", "kind": "hardware", "policy": "preserve", "rect": [0, 0, 24, 24]},
                {"id": "fab", "kind": "fabric", "policy": "texture_allowed", "rect": [32, 32, 24, 24]},
            ]
            runner = create_restoration_runner("imported", imported_dir=root)
            res = runner.run(
                src,
                scale=4,
                rois=rois,
                roi_space="target",
                apply_texture_guard=True,
                case_id="sample",
            )
            self.assertTrue(res.provenance.texture_guard_applied)
            self.assertIsNotNone(res.guard_receipt)
            self.assertIsNotNone(res.drift_report)
            self.assertEqual(res.drift_report["locked_pixel_mismatches"], 0)
            # Protected hardware region must equal base_4x byte-for-byte
            np.testing.assert_array_equal(res.image[0:24, 0:24], base_4x[0:24, 0:24])
            # Interior texture region must differ from base_4x (candidate blended in)
            self.assertFalse(np.array_equal(res.image[32:56, 32:56], base_4x[32:56, 32:56]))

    def test_to_comparator_runner_adapter_contract(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src_path = root / "src.png"
            dest_path = root / "out" / "fidelis.png"
            src = _make_textured_rgb(16, 16)
            Image.fromarray(src).save(src_path)

            case = {
                "id": "case_1",
                "split": "held_out",
                "category": "apparel",
                "source_path": "src.png",
                "source_dimensions": [16, 16],
                "target_dimensions": [64, 64],
            }
            runner = RestorationRunner(BicubicBaselineBackend(model_id="bicubic_test"))
            comp_fn = runner.to_comparator_runner()

            out = comp_fn(case, src_path, dest_path)
            self.assertEqual(out.status, "completed")
            self.assertEqual(out.output_path, dest_path)
            self.assertTrue(dest_path.is_file())
            self.assertEqual(out.settings["backend"], "bicubic")

            rej = comp_fn({**case, "expected_behavior": "reject_unsupported_input"}, src_path, dest_path)
            self.assertEqual(rej.status, "rejected_unsupported")
            self.assertIsNone(rej.output_path)

    def test_unknown_backend_raises(self) -> None:
        with self.assertRaises(ValueError):
            create_restoration_runner("nonexistent_backend")


if __name__ == "__main__":
    unittest.main()
