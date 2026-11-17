"""Offline regression checks for fail-closed quality reporting."""
import unittest

from fidelis.eval.metric_contract import format_quality_summary


class MetricContractTests(unittest.TestCase):
    def test_missing_reference_suppresses_legacy_defaults(self):
        text = format_quality_summary({"psnr": 29.5, "ssim": 0.89, "lpips": 0.14})
        self.assertIn("unavailable", text)
        self.assertNotIn("29.5", text)

    def test_ground_truth_requires_no_fake_lpips(self):
        text = format_quality_summary({"psnr": 32.125, "ssim": 0.92}, reference_kind="ground_truth")
        self.assertIn("32.12 dB", text)
        self.assertIn("ground-truth reference", text)
        self.assertIn("no LPIPS measured", text)

    def test_source_consistency_is_not_accuracy(self):
        text = format_quality_summary({"psnr": 29, "ssim": 0.8}, reference_kind="source_consistency")
        self.assertIn("not recovery accuracy", text)

    def test_rejects_pseudo_lpips(self):
        with self.assertRaises(ValueError):
            format_quality_summary({"psnr": 30, "ssim": 0.9, "lpips": 0.1}, reference_kind="ground_truth")

    def test_missing_or_nonfinite_metrics_not_reported(self):
        for metrics in ({}, {"psnr": float("nan"), "ssim": 0.9}, {"psnr": 20, "ssim": float("inf")}, {"psnr": 20, "ssim": 1.5}):
            with self.subTest(metrics=metrics):
                self.assertIn("unavailable", format_quality_summary(metrics, reference_kind="ground_truth"))

    def test_rejects_unrecognized_reference(self):
        with self.assertRaises(ValueError):
            format_quality_summary({"psnr": 30, "ssim": 0.9}, reference_kind="bicubic")


if __name__ == "__main__":
    unittest.main()
