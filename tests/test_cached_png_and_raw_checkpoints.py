"""Regression tests for validated cached full-grid PNGs and raw inference checkpoints (#135)."""

from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PIL import Image, ImageCms

from fidelis.engine import (
    CheckpointError,
    CheckpointRestorationBackend,
    RestorationRunner,
    create_restoration_runner,
    make_raw_checkpoint_callback,
)
from fidelis.eval.corpus_manifest import inspect_image
from fidelis.studio.audition import run_model_vs_bicubic_audition
from fidelis.studio.png import (
    PngPixelLimit,
    inspect_cached_generated_png,
    read_cached_generated_png,
    read_export_pass,
    read_rgb8_png,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _make_pattern_rgb(h: int = 32, w: int = 32, seed: int = 19) -> np.ndarray:
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:h, 0:w]
    base = (110 + 45 * np.sin(xx * 0.45) * np.cos(yy * 0.45)).astype(np.int16)
    noise = rng.integers(-12, 13, size=(h, w, 3), dtype=np.int16)
    return np.clip(base[..., None] + noise, 0, 255).astype(np.uint8)


class CachedGeneratedPngValidationTests(unittest.TestCase):
    def test_low_pillow_limit_preserves_public_bombs_while_reading_validated_cached_png(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            arr = _make_pattern_rgb(64, 64)
            png_path = root / "cached_4x.png"
            Image.fromarray(arr).save(png_path, format="PNG")
            raw_bytes = png_path.read_bytes()

            # Deliberately lower Pillow's global limit well below 64*64 = 4096 pixels.
            # Pillow raises DecompressionBombError when pixels > 2 * MAX_IMAGE_PIXELS.
            with patch.object(Image, "MAX_IMAGE_PIXELS", 1000):
                self.assertEqual(Image.MAX_IMAGE_PIXELS, 1000)
                with self.assertRaises(Image.DecompressionBombError):
                    with Image.open(png_path) as im:
                        im.load()
                with self.assertRaises((Image.DecompressionBombError, PngPixelLimit)):
                    read_rgb8_png(io.BytesIO(raw_bytes))
                with self.assertRaises((Image.DecompressionBombError, PngPixelLimit)):
                    read_export_pass(png_path)
                with self.assertRaises((Image.DecompressionBombError, ValueError)):
                    inspect_image(png_path)

                meta = inspect_cached_generated_png(
                    png_path, expected_size=(64, 64), expected_mode="RGB", verify_crc=True
                )
                self.assertEqual(meta["dimensions"], [64, 64])
                self.assertEqual(meta["mode"], "RGB")
                self.assertEqual(meta["format"], "PNG")
                self.assertTrue(meta["iend_complete"])

                decoded, _ = read_cached_generated_png(
                    png_path, expected_size=(64, 64), expected_mode="RGB", verify_crc=True
                )
                np.testing.assert_array_equal(decoded, arr)
                self.assertEqual(Image.MAX_IMAGE_PIXELS, 1000)

                # Also exercise pure-Python scanline fallback when cv2 is absent.
                with patch.dict(sys.modules, {"cv2": None}):
                    decoded_pure, _ = read_cached_generated_png(
                        png_path, expected_size=(64, 64), expected_mode="RGB"
                    )
                    np.testing.assert_array_equal(decoded_pure, arr)
                self.assertEqual(Image.MAX_IMAGE_PIXELS, 1000)

    def test_cached_png_rejects_mismatch_mode_truncation_apng_and_icc(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            arr = _make_pattern_rgb(32, 32)
            rgb_path = root / "rgb.png"
            Image.fromarray(arr).save(rgb_path, format="PNG")

            with self.assertRaisesRegex(ValueError, "silent resizing is forbidden"):
                read_cached_generated_png(rgb_path, expected_size=(32, 30))

            with self.assertRaises(PngPixelLimit):
                read_cached_generated_png(rgb_path, expected_size=(32, 32), max_pixels=500)

            rgba_path = root / "rgba.png"
            Image.new("RGBA", (32, 32), (10, 20, 30, 255)).save(rgba_path, format="PNG")
            with self.assertRaisesRegex(ValueError, "mode/depth mismatch"):
                inspect_cached_generated_png(rgba_path, expected_size=(32, 32), expected_mode="RGB")

            profiled_path = root / "icc.png"
            profile = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
            Image.fromarray(arr).save(profiled_path, format="PNG", icc_profile=profile)
            with self.assertRaisesRegex(ValueError, "ICC profile"):
                inspect_cached_generated_png(profiled_path, expected_size=(32, 32))

            apng_path = root / "anim.png"
            f1 = Image.new("RGB", (16, 16), (1, 2, 3))
            f2 = Image.new("RGB", (16, 16), (4, 5, 6))
            f1.save(apng_path, format="PNG", save_all=True, append_images=[f2], duration=[50, 50])
            with self.assertRaisesRegex(ValueError, "Animated"):
                inspect_cached_generated_png(apng_path, expected_size=(16, 16))

            truncated_path = root / "truncated.png"
            truncated_path.write_bytes(rgb_path.read_bytes()[:-12])
            with self.assertRaisesRegex(ValueError, "incomplete|Truncated"):
                inspect_cached_generated_png(truncated_path, expected_size=(32, 32))

            trailing_path = root / "trailing.png"
            trailing_path.write_bytes(rgb_path.read_bytes() + b"extra")
            with self.assertRaisesRegex(ValueError, "Trailing bytes"):
                inspect_cached_generated_png(trailing_path, expected_size=(32, 32))

    def test_actual_preserved_twill_cached_pngs_if_present(self) -> None:
        case_dir = (
            Path.home()
            / "melato-corpus/fidelis/release-evidence/53f1995/twill-swinir/cases/tex_cotton_twill_chino"
        )
        cand_path = case_dir / "candidate_4x.png"
        bic_path = case_dir / "bicubic_4x.png"
        if not (cand_path.is_file() and bic_path.is_file()):
            self.skipTest("Private preserved 198.7 MP twill PNGs not present on this host")

        for artifact in (cand_path, bic_path):
            with self.assertRaises(Image.DecompressionBombError):
                with Image.open(artifact) as im:
                    im.load()
            meta = inspect_cached_generated_png(
                artifact, expected_size=(17404, 11416), expected_mode="RGB"
            )
            self.assertEqual(meta["dimensions"], [17404, 11416])
            self.assertEqual(meta["mode"], "RGB")
            self.assertTrue(meta["iend_complete"])


class RawInferenceCheckpointAndReplayTests(unittest.TestCase):
    def _build_oversharpened_raw_and_rois(self, h: int = 24, w: int = 24):
        src = _make_pattern_rgb(h, w, seed=31)
        bic = np.asarray(
            Image.fromarray(src).resize((w * 4, h * 4), Image.Resampling.BICUBIC),
            dtype=np.uint8,
        )
        # Put a steep edge inside a preserved ROI (top-left 32x32 on 4x grid) and
        # add severe oversharpening / ringing along that edge in raw_candidate.
        # Guarded output will lock those preserved pixels back to bicubic, so only
        # raw_candidate exposes FAIL_SHARPENING_ONLY!
        src_edge = src.copy()
        src_edge[:, :4] = 30
        src_edge[:, 4:8] = 225
        bic = np.asarray(
            Image.fromarray(src_edge).resize((w * 4, h * 4), Image.Resampling.BICUBIC),
            dtype=np.uint8,
        )
        raw = bic.copy()
        # Inject strong halo ringing on both sides of the contour inside the preserve ROI [0, 0, 32, 96].
        raw[:, 10:15] = 0
        raw[:, 15:20] = 255
        raw[:, 20:25] = 0
        # Give fabric ROI some gentle detail so interior texture passes on guarded output.
        y4, x4 = np.mgrid[0 : h * 4, 0 : w * 4]
        delta = (8 * np.sin(x4 * 1.1) * np.cos(y4 * 1.1)).astype(np.int16)
        raw[:, 32:] = np.clip(bic[:, 32:].astype(np.int16) + delta[:, 32:, None], 0, 255).astype(np.uint8)
        rois = [
            {"id": "zipper", "kind": "hardware", "policy": "preserve", "rect": [0, 0, 32, h * 4]},
            {"id": "weave", "kind": "fabric", "policy": "texture_allowed", "rect": [32, 0, w * 4 - 32, h * 4]},
        ]
        return src_edge, bic, raw, rois

    def test_post_inference_failure_persists_raw_checkpoint_before_guard_and_replays_zero_inference(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src_rgb, bic_4x, raw_4x, rois = self._build_oversharpened_raw_and_rois()
            src_path = root / "case_src.png"
            Image.fromarray(src_rgb).save(src_path, format="PNG")
            src_file_sha = hashlib.sha256(src_path.read_bytes()).hexdigest()

            calls = {"count": 0}

            class _CountingBackend:
                model_id = "oversharpen_test_model"
                backend_name = "counting_test"
                weights_sha256 = "b" * 64

                def restore(self, source_rgb, *, base_4x, scale, target_shape, case_id=None):
                    calls["count"] += 1
                    return raw_4x.copy(), {"device": "cpu", "tile_core": 64}

            ckpt_dir = root / "checkpoints" / "case1"
            saved_record: dict = {}
            callback = make_raw_checkpoint_callback(
                ckpt_dir,
                source_file_sha256=src_file_sha,
                source_path=src_path,
                protocol_sha256="p" * 64,
                config_sha256="c" * 64,
                out_record=saved_record,
            )

            runner = RestorationRunner(_CountingBackend())
            # Inject a failure AFTER backend.restore + exact-shape validation, inside compose_regions!
            with patch(
                "fidelis.engine.restoration_runner.compose_regions",
                side_effect=RuntimeError("injected post-inference composition crash"),
            ):
                with self.assertRaisesRegex(RuntimeError, "injected post-inference"):
                    runner.run(
                        src_rgb,
                        scale=4,
                        rois=rois,
                        roi_space="target",
                        case_id="case1",
                        raw_checkpoint_callback=callback,
                    )

            self.assertEqual(calls["count"], 1)
            self.assertTrue((ckpt_dir / "raw_candidate.npy").is_file())
            self.assertTrue((ckpt_dir / "bicubic_base.npy").is_file())
            self.assertTrue((ckpt_dir / "checkpoint_receipt.json").is_file())
            self.assertIn("receipt_sha256", saved_record)

            # Replay via run_model_vs_bicubic_audition with NO inference backend loaded/called.
            out_dir = root / "replay_audition"
            with patch.dict(sys.modules, {"torch": None, "spandrel": None, "onnxruntime": None}):
                report = run_model_vs_bicubic_audition(
                    [
                        {
                            "id": "case1",
                            "source_path": str(src_path),
                            "rois": rois,
                            "roi_space": "target",
                            "split": "calibration",
                        }
                    ],
                    runner=None,
                    output_dir=out_dir,
                    generate_html=False,
                    replay_checkpoint_dir=root / "checkpoints",
                    protocol_sha256="p" * 64,
                    config_sha256="c" * 64,
                )

            self.assertEqual(calls["count"], 1)
            self.assertFalse(report["model"]["inference_executed"])
            case_entry = report["cases"][0]
            self.assertFalse(case_entry["inference_executed"])
            self.assertFalse(case_entry["provenance"]["extra"]["inference_executed"])
            self.assertIn("original_generation_identity", case_entry)
            self.assertIn("evaluation_identity", case_entry)
            # Raw oversharpening inside the preserved ROI is preserved behind protected final pixels!
            self.assertEqual(case_entry["outcome"]["outcome"], "FAIL_SHARPENING_ONLY")
            self.assertFalse(case_entry["outcome"]["passed"])
            # Guarded candidate_4x.png still protected the zipper ROI to match bicubic_4x.png!
            cand_final, _ = read_cached_generated_png(case_entry["candidate_path"], expected_size=(96, 96))
            bic_final, _ = read_cached_generated_png(case_entry["bicubic_path"], expected_size=(96, 96))
            np.testing.assert_array_equal(cand_final[:, :32], bic_final[:, :32])

    def test_cli_audition_melato_save_and_replay_checkpoints(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = _make_pattern_rgb(16, 16, seed=9)
            src_path = root / "sample.png"
            imp_dir = root / "imp"
            imp_dir.mkdir()
            Image.fromarray(src).save(src_path)
            bic = np.asarray(Image.fromarray(src).resize((64, 64), Image.Resampling.BICUBIC), dtype=np.uint8)
            Image.fromarray(bic).save(imp_dir / "sample.png")

            manifest_path = root / "manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "cases": [
                            {
                                "id": "sample",
                                "source_path": str(src_path),
                                "split": "calibration",
                                "roi_space": "source",
                                "rois": [
                                    {"id": "fab", "kind": "fabric", "policy": "texture_allowed", "rect": [2, 2, 12, 12]}
                                ],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            ckpt_root = root / "ckpts"
            save_proc = subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / "scripts" / "audition-melato.py"),
                    "--manifest",
                    str(manifest_path),
                    "--backend",
                    "imported",
                    "--imported-dir",
                    str(imp_dir),
                    "--no-html",
                    "--raw-checkpoint-dir",
                    str(ckpt_root),
                    "--output-dir",
                    str(root / "run1"),
                ],
                cwd=str(REPO_ROOT),
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(save_proc.returncode, 0, msg=save_proc.stdout + save_proc.stderr)
            self.assertTrue((ckpt_root / "sample" / "checkpoint_receipt.json").is_file())

            replay_out = root / "run2"
            replay_proc = subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / "scripts" / "audition-melato.py"),
                    "--manifest",
                    str(manifest_path),
                    "--no-html",
                    "--replay-checkpoint-dir",
                    str(ckpt_root),
                    "--output-dir",
                    str(replay_out),
                ],
                cwd=str(REPO_ROOT),
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(replay_proc.returncode, 0, msg=replay_proc.stdout + replay_proc.stderr)
            replay_report = json.loads((replay_out / "audition_report.json").read_text(encoding="utf-8"))
            self.assertFalse(replay_report["model"]["inference_executed"])
            self.assertFalse(replay_report["cases"][0]["inference_executed"])

    def test_checkpoint_rejects_guarded_png_partial_pub_path_escape_and_all_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src_rgb, bic_4x, raw_4x, rois = self._build_oversharpened_raw_and_rois(16, 16)
            src_path = root / "src.png"
            Image.fromarray(src_rgb).save(src_path, format="PNG")
            src_sha = hashlib.sha256(src_path.read_bytes()).hexdigest()

            class _StubBackend:
                model_id = "stub_model"
                backend_name = "stub_backend"
                weights_sha256 = "d" * 64
                device = "cpu"
                tile_core = 32
                tile_context = 8

                def restore(self, source_rgb, *, base_4x, scale, target_shape, case_id=None):
                    return raw_4x.copy(), {"device": "cpu", "tile_core": 32, "tile_context": 8}

            ckpt_dir = root / "ckpt"
            cb = make_raw_checkpoint_callback(
                ckpt_dir,
                source_file_sha256=src_sha,
                source_path=src_path,
                protocol_sha256="e" * 64,
                config_sha256="f" * 64,
            )
            RestorationRunner(_StubBackend()).run(
                src_rgb,
                scale=4,
                rois=rois,
                roi_space="target",
                case_id="c_tamper",
                raw_checkpoint_callback=cb,
            )

            # Helper to clone a clean checkpoint directory for isolated tamper tests.
            def _clone_ckpt(name: str) -> Path:
                dst = root / name
                dst.mkdir()
                for f in ckpt_dir.iterdir():
                    dst.joinpath(f.name).write_bytes(f.read_bytes())
                return dst

            # 1. Guarded candidate_4x.png / guarded role must never be accepted as raw.
            c_png = _clone_ckpt("c_png")
            Image.fromarray(bic_4x).save(c_png / "candidate_4x.png", format="PNG")
            rec = json.loads((c_png / "checkpoint_receipt.json").read_text(encoding="utf-8"))
            rec["artifacts"]["raw_candidate"]["path"] = "candidate_4x.png"
            (c_png / "checkpoint_receipt.json").write_text(json.dumps(rec), encoding="utf-8")
            with self.assertRaises(CheckpointError):
                CheckpointRestorationBackend(c_png)

            c_role = _clone_ckpt("c_role")
            rec = json.loads((c_role / "checkpoint_receipt.json").read_text(encoding="utf-8"))
            rec["artifacts"]["raw_candidate"]["role"] = "guarded_final"
            (c_role / "checkpoint_receipt.json").write_text(json.dumps(rec), encoding="utf-8")
            with self.assertRaises(CheckpointError):
                CheckpointRestorationBackend(c_role)

            # 2. Partial publication (missing receipt or missing .npy).
            c_no_rec = _clone_ckpt("c_no_rec")
            (c_no_rec / "checkpoint_receipt.json").unlink()
            with self.assertRaises(CheckpointError):
                CheckpointRestorationBackend(c_no_rec)

            c_no_raw = _clone_ckpt("c_no_raw")
            (c_no_raw / "raw_candidate.npy").unlink()
            with self.assertRaises(CheckpointError):
                CheckpointRestorationBackend(c_no_raw)

            # 3. Path escape via .. and symlink.
            c_escape = _clone_ckpt("c_escape")
            rec = json.loads((c_escape / "checkpoint_receipt.json").read_text(encoding="utf-8"))
            rec["artifacts"]["raw_candidate"]["path"] = "../ckpt/raw_candidate.npy"
            (c_escape / "checkpoint_receipt.json").write_text(json.dumps(rec), encoding="utf-8")
            with self.assertRaises(CheckpointError):
                CheckpointRestorationBackend(c_escape)

            c_symlink = _clone_ckpt("c_symlink")
            outside = root / "outside_raw.npy"
            outside.write_bytes((ckpt_dir / "raw_candidate.npy").read_bytes())
            (c_symlink / "raw_candidate.npy").unlink()
            os.symlink(outside, c_symlink / "raw_candidate.npy")
            with self.assertRaises(CheckpointError):
                CheckpointRestorationBackend(c_symlink)

            # 4. Source file SHA, source pixel SHA, model, ROI, protocol, config, scale, target_shape mismatches.
            with self.assertRaises(CheckpointError):
                CheckpointRestorationBackend(ckpt_dir, expected_source_file_sha256="0" * 64)
            with self.assertRaises(CheckpointError):
                CheckpointRestorationBackend(ckpt_dir, expected_model_id="wrong_model")
            with self.assertRaises(CheckpointError):
                CheckpointRestorationBackend(ckpt_dir, expected_weights_sha256="0" * 64)
            with self.assertRaises(CheckpointError):
                CheckpointRestorationBackend(ckpt_dir, expected_protocol_sha256="0" * 64)
            with self.assertRaises(CheckpointError):
                CheckpointRestorationBackend(ckpt_dir, expected_config_sha256="0" * 64)
            with self.assertRaises(CheckpointError):
                CheckpointRestorationBackend(ckpt_dir, expected_scale=2)
            with self.assertRaises(CheckpointError):
                CheckpointRestorationBackend(ckpt_dir, expected_target_shape=(32, 32, 3))

            bad_rois = [{"id": "zipper", "kind": "hardware", "policy": "preserve", "rect": [1, 0, 32, 64]}]
            replay_runner = create_restoration_runner("checkpoint", checkpoint_dir=ckpt_dir)
            with self.assertRaises(CheckpointError):
                replay_runner.run(src_rgb, scale=4, rois=bad_rois, roi_space="target", case_id="c_tamper")

            bad_src = src_rgb.copy()
            bad_src[0, 0, 0] ^= 1
            with self.assertRaises(CheckpointError):
                replay_runner.run(bad_src, scale=4, rois=rois, roi_space="target", case_id="c_tamper")

            # 5. Truncated / object-dtype .npy rejection.
            c_trunc = _clone_ckpt("c_trunc")
            raw_bytes = (c_trunc / "raw_candidate.npy").read_bytes()
            (c_trunc / "raw_candidate.npy").write_bytes(raw_bytes[:-1])
            rec = json.loads((c_trunc / "checkpoint_receipt.json").read_text(encoding="utf-8"))
            rec["artifacts"]["raw_candidate"]["file_bytes"] = len(raw_bytes) - 1
            rec["artifacts"]["raw_candidate"]["sha256"] = hashlib.sha256(raw_bytes[:-1]).hexdigest()
            (c_trunc / "checkpoint_receipt.json").write_text(json.dumps(rec), encoding="utf-8")
            with self.assertRaises(CheckpointError):
                CheckpointRestorationBackend(c_trunc).restore(
                    src_rgb, base_4x=bic_4x, scale=4, target_shape=(64, 64, 3), case_id="c_tamper"
                )

            c_obj = _clone_ckpt("c_obj")
            obj_arr = np.empty((64, 64, 3), dtype=object)
            obj_arr[:] = None
            with (c_obj / "raw_candidate.npy").open("wb") as fh:
                np.save(fh, obj_arr, allow_pickle=True)
            obj_bytes = (c_obj / "raw_candidate.npy").read_bytes()
            rec = json.loads((c_obj / "checkpoint_receipt.json").read_text(encoding="utf-8"))
            rec["artifacts"]["raw_candidate"]["file_bytes"] = len(obj_bytes)
            rec["artifacts"]["raw_candidate"]["sha256"] = hashlib.sha256(obj_bytes).hexdigest()
            (c_obj / "checkpoint_receipt.json").write_text(json.dumps(rec), encoding="utf-8")
            with self.assertRaises(CheckpointError):
                CheckpointRestorationBackend(c_obj).restore(
                    src_rgb, base_4x=bic_4x, scale=4, target_shape=(64, 64, 3), case_id="c_tamper"
                )


if __name__ == "__main__":
    unittest.main()
