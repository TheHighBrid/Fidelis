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

    def test_structured_payload_drops_unverified_legacy_numbers(self):
        from fidelis.eval.metric_contract import sanitize_quality_payload
        payload = sanitize_quality_payload({"psnr": 35, "ssim": 0.95, "lpips": 0.1})
        self.assertEqual(payload, {"status": "unavailable", "reason": "reference_not_verified", "metrics": {}})

    def test_structured_payload_rejects_pseudo_lpips_and_invalid_values(self):
        from fidelis.eval.metric_contract import sanitize_quality_payload
        for values in ({"psnr": 30, "ssim": 0.9, "lpips": 0.1},
                       {"psnr": float("nan"), "ssim": 0.9},
                       {"psnr": 30, "ssim": 1.1},
                       {"psnr": True, "ssim": 0.9}):
            with self.subTest(values=values):
                payload = sanitize_quality_payload(values, reference_kind="ground_truth")
                self.assertEqual(payload["metrics"], {})
                self.assertEqual(payload["status"], "unavailable")

    def test_structured_payload_distinguishes_source_consistency(self):
        from fidelis.eval.metric_contract import sanitize_quality_payload
        payload = sanitize_quality_payload({"psnr": 30, "ssim": 0.9}, reference_kind="source_consistency")
        self.assertEqual(payload["status"], "measured")
        self.assertFalse(payload["is_ground_truth"])
        self.assertEqual(payload["metrics"], {"psnr": 30.0, "ssim": 0.9})

    def test_non_mapping_payload_fails_closed(self):
        from fidelis.eval.metric_contract import sanitize_quality_payload
        for invalid in (None, [], "psnr=30", 30, True):
            with self.subTest(invalid=invalid):
                result = sanitize_quality_payload(invalid, reference_kind="ground_truth")
                self.assertEqual(result, {"status": "unavailable", "reason": "invalid_payload", "metrics": {}})
                self.assertIn("unavailable", format_quality_summary(invalid, reference_kind="ground_truth"))

    def test_unknown_reference_rejected_even_with_malformed_payload(self):
        from fidelis.eval.metric_contract import sanitize_quality_payload
        with self.assertRaises(ValueError):
            sanitize_quality_payload(None, reference_kind="untrusted")


    def test_legacy_manifest_removes_nested_quality_claims_without_mutation(self):
        from fidelis.eval.metric_contract import sanitize_legacy_manifest
        original = {
            "metrics": {"psnr": 29.5, "ssim": 0.89, "lpips": 0.14},
            "spans": [{"name": "upscale_pipeline", "attributes": {
                "psnr": 29.5, "ssim": 0.89, "lpips": 0.14,
                "cielab_delta_e": 0.8, "gradient_coherence_pct": 92,
                "elapsed_ms": 123}}],
            "output_sha256": "abc",
        }
        sanitized = sanitize_legacy_manifest(original)
        self.assertEqual(sanitized["metrics"]["status"], "unavailable")
        self.assertEqual(sanitized["metrics"]["metrics"], {})
        self.assertEqual(sanitized["spans"][0]["attributes"], {"elapsed_ms": 123})
        self.assertEqual(sanitized["output_sha256"], "abc")
        self.assertEqual(original["spans"][0]["attributes"]["psnr"], 29.5)

    def test_legacy_manifest_handles_malformed_spans(self):
        from fidelis.eval.metric_contract import sanitize_legacy_manifest
        sanitized = sanitize_legacy_manifest({"metrics": None, "spans": [None, "bad", {"attributes": None}]})
        self.assertEqual(sanitized["metrics"]["metrics"], {})
        self.assertEqual(len(sanitized["spans"]), 3)

    def test_legacy_manifest_redacts_nested_span_quality_without_losing_evidence(self):
        from fidelis.eval.metric_contract import sanitize_legacy_manifest
        original = {
            "metrics": {"psnr": 31},
            "spans": [
                {"attributes": {
                    "diagnostics": {"quality": {"psnr": 31, "lpips": 0.2, "elapsed_ms": 10}},
                    "tiles": [{"ssim": 0.8, "hash": "sha"}, None,
                              {"nested": [{"gradient_coherence_pct": 95, "note": "ok"}]}],
                    "output_sha256": "abc",
                }},
                {"attributes": ["unexpected", {"cielab_delta_e": 2, "duration_ms": 9}]},
            ],
            "output_sha256": "top-level-hash",
        }
        sanitized = sanitize_legacy_manifest(original)
        attrs = sanitized["spans"][0]["attributes"]
        self.assertEqual(attrs["diagnostics"]["quality"], {"elapsed_ms": 10})
        self.assertEqual(attrs["tiles"], [{"hash": "sha"}, None, {"nested": [{"note": "ok"}]}])
        self.assertEqual(attrs["output_sha256"], "abc")
        self.assertEqual(sanitized["spans"][1]["attributes"], ["unexpected", {"duration_ms": 9}])
        self.assertEqual(sanitized["output_sha256"], "top-level-hash")
        self.assertEqual(original["spans"][0]["attributes"]["diagnostics"]["quality"]["psnr"], 31)

    def test_legacy_manifest_redacts_span_events_and_direct_quality_fields(self):
        from fidelis.eval.metric_contract import sanitize_legacy_manifest
        original = {
            "metrics": {"psnr": 30},
            "spans": [{
                "name": "quality-check", "psnr": 30,
                "events": [{"name": "sample", "lpips": 0.3,
                            "payload": {"ssim": 0.9, "duration_ms": 7}}],
                "attributes": {"output_sha256": "abc"},
            }],
            "output_sha256": "top-level-hash",
        }
        sanitized = sanitize_legacy_manifest(original)
        span = sanitized["spans"][0]
        self.assertNotIn("psnr", span)
        self.assertEqual(span["events"], [{"name": "sample",
                                           "payload": {"duration_ms": 7}}])
        self.assertEqual(span["attributes"]["output_sha256"], "abc")
        self.assertEqual(sanitized["output_sha256"], "top-level-hash")
        self.assertEqual(original["spans"][0]["psnr"], 30)

    def test_legacy_manifest_preserves_unrelated_quality_named_metadata(self):
        from fidelis.eval.metric_contract import sanitize_legacy_manifest
        record = {
            "metrics": {},
            "quality_review_status": "pending",
            "spans": [{"attributes": {"quality_review_status": "pending",
                                      "model_metadata": {"license": "unknown"}}}],
        }
        sanitized = sanitize_legacy_manifest(record)
        self.assertEqual(sanitized["quality_review_status"], "pending")
        self.assertEqual(sanitized["spans"][0]["attributes"]["model_metadata"],
                         {"license": "unknown"})

    def test_legacy_manifest_redacts_auxiliary_telemetry_and_root_claims(self):
        from fidelis.eval.metric_contract import sanitize_legacy_manifest
        original = {
            "psnr": 42, "metrics": {"psnr": 42, "lpips": 0.1},
            "telemetry": {"quality": {"ssim": 0.98, "elapsed_ms": 5}},
            "events": [{"lpips": 0.1, "output_sha256": "sha"}],
            "metadata": {"nested": [{"cielab_delta_e": 1.2, "model": "local"}]},
            "output_sha256": "top-hash",
        }
        sanitized = sanitize_legacy_manifest(original)
        self.assertNotIn("psnr", sanitized)
        self.assertEqual(sanitized["metrics"]["status"], "unavailable")
        self.assertEqual(sanitized["telemetry"]["quality"], {"elapsed_ms": 5})
        self.assertEqual(sanitized["events"], [{"output_sha256": "sha"}])
        self.assertEqual(sanitized["metadata"]["nested"], [{"model": "local"}])
        self.assertEqual(sanitized["output_sha256"], "top-hash")
        self.assertEqual(original["telemetry"]["quality"]["ssim"], 0.98)

    def test_legacy_manifest_redacts_case_variant_metric_keys(self):
        from fidelis.eval.metric_contract import sanitize_legacy_manifest
        original = {
            "PSNR": 42,
            "metrics": {"psnr": 42},
            "spans": [{"attributes": {
                "SSIM": 0.99, "LPIPS": 0.01,
                "nested": [{"CieLab_Delta_E": 1.2, "hash": "safe"}],
                "elapsed_ms": 12,
            }}],
            "output_sha256": "original",
        }
        sanitized = sanitize_legacy_manifest(original)
        self.assertNotIn("PSNR", sanitized)
        self.assertEqual(sanitized["spans"][0]["attributes"],
                         {"nested": [{"hash": "safe"}], "elapsed_ms": 12})
        self.assertEqual(sanitized["output_sha256"], "original")
        self.assertEqual(original["spans"][0]["attributes"]["SSIM"], 0.99)

if __name__ == "__main__":
    unittest.main()
