"""Regression tests for F12 comparator runners and blind pairwise scoring."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import numpy as np
from PIL import Image

from fidelis.eval.comparators import (
    CANONICAL_COMPARATORS,
    ComparatorOutput,
    bicubic_runner,
    build_blind_pairwise_manifest,
    run_comparators,
    summarize_blind_reviews,
)
from fidelis.eval.corpus_manifest import digest, file_hash, freeze, inspect_image

REPO = Path(__file__).resolve().parents[1]
PROTOCOL = json.loads((REPO / "config/benchmark/protocol-v1.json").read_text(encoding="utf-8"))
SLOTS = json.loads((REPO / "config/benchmark/slots-v1.json").read_text(encoding="utf-8"))


class ComparatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        evidence = self.root / "fixture-rights.txt"
        evidence.write_text("Fixture declaration only.", encoding="utf-8")
        review = {
            "status": "approved",
            "reviewed_by": "test-fixture",
            "reviewed_at": "2026-11-10",
            "evidence_path": evidence.name,
            "evidence_sha256": file_hash(evidence),
        }
        self.manifest = {
            "schema_version": 1,
            "protocol_sha256": digest(PROTOCOL),
            "slots_sha256": digest(SLOTS),
            "cases": [],
            "coverage_review": copy.deepcopy(review),
        }
        for i, slot in enumerate(SLOTS["slots"]):
            src_path = self.root / f"img-{i:02d}.png"
            arr = np.full((6, 8, 3), (i * 3 % 200) + 20, dtype=np.uint8)
            Image.fromarray(arr, "RGB").save(src_path)
            src_info = {"path": src_path.name, **inspect_image(src_path)}
            # Mark last case remote-allowed to verify per-case remote permission enforcement.
            remote_perm = "allowed" if i == len(SLOTS["slots"]) - 1 else "denied"
            self.manifest["cases"].append(
                {
                    "id": f"case-{i:02d}",
                    "role": "production",
                    "slot_id": slot["id"],
                    "category": slot["category"],
                    "source_kind": "photograph",
                    "source": src_info,
                    "leakage_group": f"grp-{i}",
                    "rights": {
                        **review,
                        "local_evaluation": True,
                        "subject_consent": "not_required",
                        "remote_processing": remote_perm,
                        "basis": "synthetic test fixture",
                    },
                    "target_dimensions": [16, 12],
                    "expected_behavior": "enhance",
                    "rois": [{"id": "roi1", "kind": "logo", "policy": "preserve", "rect": [1, 1, 4, 3]}],
                    "known_text": [],
                    "text_review": "completed",
                }
            )
        self.lock = freeze(self.manifest, PROTOCOL, SLOTS, self.root)

    def test_frozen_lock_comparators_remote_guard_and_honest_unavailability(self) -> None:
        out_dir = self.root / "out"
        clarity_calls: list[str] = []

        def mock_fidelis(case: dict, src: Path, dest: Path) -> ComparatorOutput:
            dest.parent.mkdir(parents=True, exist_ok=True)
            with Image.open(src) as im:
                im.resize(tuple(case["target_dimensions"]), Image.Resampling.BICUBIC).save(dest)
            return ComparatorOutput(
                output_path=dest,
                status="completed",
                settings={"profile": "luxury_apparel", "fixture": True},
                elapsed_seconds=0.01,
                cost_usd=0.0,
            )

        def mock_clarity(case: dict, src: Path, dest: Path) -> ComparatorOutput:
            clarity_calls.append(case["id"])
            return ComparatorOutput(
                output_path=None,
                status="unavailable",
                settings={},
                error="Clarity key unconfigured",
            )

        def mock_vosr(case: dict, _src: Path, _dest: Path) -> ComparatorOutput:
            raise RuntimeError("Simulated challenger crash")

        report = run_comparators(
            self.lock,
            asset_root=self.root,
            output_dir=out_dir,
            runners={
                "fidelis": mock_fidelis,
                "pinned_clarity": mock_clarity,
                "vosr_challenger": mock_vosr,
            },
        )
        self.assertEqual(report["corpus_mode"], "frozen_production_lock")
        self.assertEqual(report["case_count"], 60)
        self.assertTrue(report["single_image_per_file"])

        # Remote comparator was only invoked for the 1 case where remote_processing == "allowed".
        self.assertEqual(clarity_calls, ["case-59"])
        self.assertEqual(report["comparators"]["pinned_clarity"]["skipped_remote_disallowed"], 59)
        self.assertEqual(report["comparators"]["pinned_clarity"]["unavailable"], 1)
        self.assertEqual(report["comparators"]["dated_krea"]["skipped_remote_disallowed"], 59)
        self.assertEqual(report["comparators"]["dated_krea"]["unavailable"], 1)

        # Crashes are counted in failure tallies; interpolation & fidelis completed cleanly.
        self.assertEqual(report["comparators"]["vosr_challenger"]["failed"], 60)
        self.assertEqual(report["comparators"]["interpolation"]["completed"], 60)
        self.assertEqual(report["comparators"]["fidelis"]["completed"], 60)
        self.assertEqual(report["comparators"]["selected_deterministic_base"]["unavailable"], 60)

        first = report["cases"][0]["outputs"]["fidelis"]
        self.assertIsNotNone(first["output_sha256"])
        self.assertEqual(first["output_dimensions"], [16, 12])
        self.assertIsNone(first["metrics"]["lpips"])
        self.assertEqual(first["metric_context"]["reference"], "source_consistency")
        self.assertEqual(first["metric_context"]["lpips_status"], "not_computed")
        self.assertTrue(Path(first["output_path"]).is_file())

    def test_mismatched_dimensions_and_unfrozen_manifest_fail_closed(self) -> None:
        with self.assertRaises(ValueError):
            run_comparators(
                self.manifest,
                asset_root=self.root,
                output_dir=self.root / "bad_out",
                protocol=PROTOCOL,
                slots=SLOTS,
            )

        def wrong_size_runner(_case: dict, src: Path, dest: Path) -> ComparatorOutput:
            dest.parent.mkdir(parents=True, exist_ok=True)
            Image.new("RGB", (20, 12), (90, 90, 90)).save(dest)
            return ComparatorOutput(output_path=dest, status="completed", settings={})

        mini_manifest = copy.deepcopy(self.manifest)
        mini_manifest["cases"] = mini_manifest["cases"][:2]
        mini_manifest["cases"][0]["role"] = "regression"
        mini_manifest["cases"][0]["slot_id"] = None
        mini_manifest["cases"] = [mini_manifest["cases"][0]]
        rep = run_comparators(
            mini_manifest,
            asset_root=self.root,
            output_dir=self.root / "reg_out",
            runners={"selected_deterministic_base": wrong_size_runner},
            protocol=PROTOCOL,
            slots=SLOTS,
            allow_regression_manifest=True,
        )
        self.assertEqual(rep["corpus_mode"], "regression_only_unfrozen")
        self.assertEqual(rep["comparators"]["selected_deterministic_base"]["failed"], 1)
        self.assertIn("silent resizing is forbidden", rep["cases"][0]["outputs"]["selected_deterministic_base"]["error"])

    def test_blind_pairwise_ballot_bootstrap_and_gate_checks(self) -> None:
        def ok_fidelis(case: dict, src: Path, dest: Path) -> ComparatorOutput:
            dest.parent.mkdir(parents=True, exist_ok=True)
            with Image.open(src) as im:
                im.resize(tuple(case["target_dimensions"]), Image.Resampling.BICUBIC).save(dest)
            return ComparatorOutput(output_path=dest, status="completed", settings={"fixture": True}, cost_usd=0.0)

        report = run_comparators(
            self.lock,
            asset_root=self.root,
            output_dir=self.root / "out_blind",
            runners={"fidelis": ok_fidelis},
        )
        ballot, key_doc = build_blind_pairwise_manifest(
            report, "fidelis", "interpolation", split="held_out", seed=99
        )
        self.assertEqual(ballot["pair_count"], 30)
        self.assertTrue(all(Path(item["option_left"]).is_file() for item in ballot["items"]))
        self.assertTrue(all(Path(item["option_right"]).is_file() for item in ballot["items"]))
        self.assertTrue(all(item["option_left"] != item["option_right"] for item in ballot["items"]))
        for item in ballot["items"]:
            self.assertNotIn("fidelis", Path(item["option_left"]).name)
            self.assertNotIn("interpolation", Path(item["option_left"]).name)
            self.assertNotIn("fidelis", Path(item["option_right"]).name)
            self.assertNotIn("interpolation", Path(item["option_right"]).name)
            meta = key_doc["mapping"][item["pair_id"]]
            self.assertIn("left_output_path", meta)
            self.assertIn("right_output_path", meta)

        # Incomplete ballot cannot claim pass.
        inc = summarize_blind_reviews(ballot, key_doc, subject_comparator="fidelis", target_comparator="interpolation")
        self.assertEqual(inc["status"], "incomplete")
        self.assertFalse(inc["meets_proposed_thresholds"])

        # Score fidelis winning on 27/30 and tying on 3/30 with 0 defects -> preliminary pass (n=30 < 100).
        passing_ballot = copy.deepcopy(ballot)
        for idx, item in enumerate(passing_ballot["items"]):
            meta = key_doc["mapping"][item["pair_id"]]
            subj_side = "left" if meta["left"] == "fidelis" else "right"
            item["choice"] = "tie" if idx % 10 == 0 else subj_side
        pass_res = summarize_blind_reviews(
            passing_ballot, key_doc, subject_comparator="fidelis", target_comparator="interpolation"
        )
        self.assertEqual(pass_res["status"], "preliminary_passed")
        self.assertTrue(pass_res["preliminary_small_sample"])
        self.assertTrue(pass_res["meets_proposed_thresholds"])
        self.assertEqual(pass_res["preference_plus_tie_rate"], 1.0)
        self.assertLessEqual(pass_res["win_rate_ci95"][0], pass_res["win_rate"])

        # Adding a single critical defect fails the gate immediately.
        defect_ballot = copy.deepcopy(passing_ballot)
        m0 = key_doc["mapping"][defect_ballot["items"][0]["pair_id"]]
        if m0["left"] == "fidelis":
            defect_ballot["items"][0]["critical_defect_left"] = True
        else:
            defect_ballot["items"][0]["critical_defect_right"] = True
        fail_res = summarize_blind_reviews(
            defect_ballot, key_doc, subject_comparator="fidelis", target_comparator="interpolation"
        )
        self.assertFalse(fail_res["meets_proposed_thresholds"])
        self.assertEqual(fail_res["critical_defects_subject"], 1)

    def test_cli_run_comparators_and_summarize_on_tracked_regression_inventory(self) -> None:
        script = REPO / "scripts/run-comparators.py"
        inv_path = REPO / "config/benchmark/inventory-v1.json"

        # 1. Running against tracked inventory (target_dimensions=null) reports unavailable without crashing.
        unres = subprocess.run(
            [
                sys.executable,
                str(script),
                "run",
                str(inv_path),
                "--root",
                str(REPO),
                "--output-dir",
                str(self.root / "unres_out"),
                "--allow-regression-manifest",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        unres_json = json.loads(unres.stdout)
        self.assertEqual(unres_json["case_count"], 8)
        self.assertEqual(unres_json["comparators"]["interpolation"]["unavailable"], 8)

        # 2. Populate explicit target_dimensions on temporary copy and run interpolation + imported base + blind summary.
        inv = json.loads(inv_path.read_text(encoding="utf-8"))
        out_dir = self.root / "cli_out"
        imported = self.root / "imported_base"
        imported.mkdir()
        for case in inv["cases"]:
            sw, sh = case["source"]["dimensions"]
            case["target_dimensions"] = [sw * 2, sh * 2]
            Image.new("RGB", (sw * 2, sh * 2), (100, 120, 140)).save(imported / f"{case['id']}.png")
            (imported / f"{case['id']}.meta.json").write_text(
                json.dumps({"settings": {"model": "base-fixture"}, "cost_usd": 0.01}),
                encoding="utf-8",
            )
        scoped_inv = self.root / "regression_with_targets.json"
        scoped_inv.write_text(json.dumps(inv), encoding="utf-8")

        proc = subprocess.run(
            [
                sys.executable,
                str(script),
                "run",
                str(scoped_inv),
                "--root",
                str(REPO),
                "--output-dir",
                str(out_dir),
                "--allow-regression-manifest",
                "--imported-dir",
                f"selected_deterministic_base={imported}",
                "--blind-pair",
                "selected_deterministic_base",
                "interpolation",
                "--blind-split",
                "regression",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        res = json.loads(proc.stdout)
        self.assertEqual(res["case_count"], 8)
        self.assertEqual(res["comparators"]["interpolation"]["completed"], 8)
        self.assertEqual(res["comparators"]["selected_deterministic_base"]["completed"], 8)
        self.assertEqual(res["comparators"]["selected_deterministic_base"]["total_cost_usd"], 0.08)
        self.assertIsNone(res["comparators"]["selected_deterministic_base"]["mean_elapsed_seconds"])
        full_rep = json.loads(Path(res["report"]).read_text(encoding="utf-8"))
        self.assertTrue(
            all(
                c["outputs"]["selected_deterministic_base"]["elapsed_seconds"] is None
                for c in full_rep["cases"]
            )
        )
        self.assertEqual(res["comparators"]["fidelis"]["unavailable"], 8)

        ballot = json.loads(Path(res["blind_ballot"]).read_text(encoding="utf-8"))
        key_doc = json.loads(Path(res["blind_answer_key"]).read_text(encoding="utf-8"))
        for item in ballot["items"]:
            meta = key_doc["mapping"][item["pair_id"]]
            item["choice"] = "left" if meta["left"] == "selected_deterministic_base" else "right"
        Path(res["blind_ballot"]).write_text(json.dumps(ballot), encoding="utf-8")

        sum_proc = subprocess.run(
            [
                sys.executable,
                str(script),
                "summarize-blind",
                res["blind_ballot"],
                res["blind_answer_key"],
                "--subject",
                "selected_deterministic_base",
                "--target",
                "interpolation",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        summary = json.loads(sum_proc.stdout)
        self.assertEqual(summary["sample_count"], 8)
        self.assertTrue(summary["meets_proposed_thresholds"])

    def test_bicubic_comparator_and_scale_matched_metrics(self) -> None:
        self.assertIn("bicubic", CANONICAL_COMPARATORS)
        mini_manifest = copy.deepcopy(self.manifest)
        case0 = mini_manifest["cases"][0]
        case0["role"] = "regression"
        case0["slot_id"] = None
        mini_manifest["cases"] = [case0]

        custom_prot = copy.deepcopy(PROTOCOL)
        custom_prot["comparators"] = ["bicubic", "interpolation"]
        custom_slots = copy.deepcopy(SLOTS)
        custom_slots["protocol_sha256"] = digest(custom_prot)
        mini_manifest["protocol_sha256"] = digest(custom_prot)
        mini_manifest["slots_sha256"] = digest(custom_slots)

        dest = self.root / "direct_bicubic.png"
        src = self.root / case0["source"]["path"]
        direct = bicubic_runner(case0, src, dest)
        self.assertEqual(direct.status, "completed")
        self.assertEqual(direct.settings["method"], "bicubic")
        self.assertTrue(dest.is_file())

        report = run_comparators(
            mini_manifest,
            asset_root=self.root,
            output_dir=self.root / "bic_out",
            protocol=custom_prot,
            slots=custom_slots,
            allow_regression_manifest=True,
        )
        self.assertEqual(report["comparators"]["bicubic"]["completed"], 1)
        bic_out = report["cases"][0]["outputs"]["bicubic"]
        self.assertEqual(bic_out["settings"]["method"], "bicubic")
        self.assertIsNotNone(bic_out["scale_matched_metrics"])
        self.assertEqual(bic_out["scale_matched_metrics"]["status"], "measured")
        self.assertTrue(bic_out["scale_matched_metrics"]["all_detail_gates_passed"])


if __name__ == "__main__":
    unittest.main()
