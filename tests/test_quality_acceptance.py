"""Unit tests for calibration and held-out quality acceptance evaluation (F13 / MEL-66)."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from fidelis.eval.quality_acceptance import (
    REQUIRED_CATEGORIES,
    cohen_kappa,
    evaluate_held_out_acceptance,
    krippendorff_alpha_nominal,
    wilson_95_ci,
)


REPO_ROOT = Path(__file__).resolve().parent.parent


def _make_complete_submission(
    *,
    owner_status: str = "pending",
    include_critical_defect: bool = False,
    contaminate_split: bool = False,
    low_category: str | None = None,
) -> dict:
    ballots = []
    cal_cases = [f"{cat}-0{i}" for cat in REQUIRED_CATEGORIES for i in range(1, 7)]

    for cat in REQUIRED_CATEGORIES:
        for i in range(7, 13):
            case_id = f"{cat}-{i:02d}"
            for comp in ("pinned_clarity", "dated_krea"):
                if low_category == cat:
                    # 2 wins, 4 losses -> 33.3% preference_plus_ties (< 60%)
                    outcome = "fidelis_win" if i in (7, 8) else "comparator_win"
                else:
                    # 4 wins, 1 tie, 1 loss per category -> 66.7% win, 83.3% pref+tie
                    if i <= 10:
                        outcome = "fidelis_win"
                    elif i == 11:
                        outcome = "tie"
                    else:
                        outcome = "comparator_win"

                defects = []
                if include_critical_defect and cat == "macro" and i == 7 and comp == "pinned_clarity":
                    defects = ["text_logo_corruption"]

                ballots.append(
                    {
                        "case_id": case_id,
                        "split": "held_out",
                        "category": cat,
                        "comparator": comp,
                        "outcome": outcome,
                        "critical_defects": defects,
                    }
                )

    if contaminate_split:
        ballots.append(
            {
                "case_id": "portrait-01",
                "split": "calibration",
                "category": "portrait",
                "comparator": "pinned_clarity",
                "outcome": "fidelis_win",
                "critical_defects": [],
            }
        )

    return {
        "reproducibility_receipt": {
            "code_sha": "f84287993c9bc213dc47859b297a5a275381101d",
            "corpus_lock_sha256": "a" * 64,
            "calibration_recipe_sha256": "b" * 64,
            "runtime_versions": {"python": "3.12.15", "ncnn": "20250503"},
            "model_weight_hashes": {"RealeSR-general-v3": "c" * 64},
            "seed_policy": "fixed_seed_42",
            "colour_path": "linear-sRGB-compositor-v1",
            "provenance_status": "unsigned_execution_record",
        },
        "calibration_summary": {
            "recipe_frozen": True,
            "case_ids": cal_cases,
        },
        "required_comparators": ["pinned_clarity", "dated_krea"],
        "held_out_ballots": ballots,
        "owner_creative_signoff": {
            "status": owner_status,
            "reviewer": "Creative Director" if owner_status == "approved" else None,
            "signed_at": "2026-11-10T16:00:00Z" if owner_status == "approved" else None,
        },
    }


class QualityAcceptanceTests(unittest.TestCase):
    def test_wilson_confidence_interval_bounds(self) -> None:
        lo, hi = wilson_95_ci(25, 30)
        self.assertGreater(lo, 0.65)
        self.assertLess(hi, 0.94)
        self.assertEqual(wilson_95_ci(0, 0), (0.0, 0.0))

    def test_cohen_kappa_and_krippendorff_alpha_nominal(self) -> None:
        a = ["fidelis_win", "fidelis_win", "tie", "comparator_win", "fidelis_win"]
        b = ["fidelis_win", "tie", "tie", "comparator_win", "fidelis_win"]
        self.assertEqual(cohen_kappa(a, a), 1.0)
        kappa = cohen_kappa(a, b)
        self.assertIsNotNone(kappa)
        self.assertGreater(kappa, 0.5)
        self.assertLess(kappa, 1.0)
        self.assertIsNone(cohen_kappa([], []))

        units_perfect = [[x, x] for x in a]
        self.assertEqual(krippendorff_alpha_nominal(units_perfect), 1.0)
        units_paired = [[x, y] for x, y in zip(a, b)]
        alpha = krippendorff_alpha_nominal(units_paired)
        self.assertIsNotNone(alpha)
        self.assertGreater(alpha, 0.5)
        self.assertLess(alpha, 1.0)

        sub = _make_complete_submission(owner_status="pending")
        dual_ballots = []
        for entry in sub["held_out_ballots"]:
            dual_ballots.append({**entry, "reviewer_id": "reviewer_1"})
            dual_ballots.append({**entry, "reviewer_id": "reviewer_2"})
        sub["held_out_ballots"] = dual_ballots
        report = evaluate_held_out_acceptance(sub)
        ira = report["inter_rater_agreement"]
        self.assertEqual(ira["reviewer_count"], 2)
        self.assertEqual(ira["overlapping_pair_count"], 60)
        self.assertEqual(ira["cohen_kappa"], 1.0)
        self.assertEqual(ira["krippendorff_alpha_nominal"], 1.0)

    def test_passing_quantitative_gates_waits_for_owner_signoff_then_accepts(self) -> None:
        pending_sub = _make_complete_submission(owner_status="pending")
        report_pending = evaluate_held_out_acceptance(pending_sub)
        self.assertTrue(report_pending["quantitative_gates_passed"])
        self.assertEqual(report_pending["overall_status"], "awaiting_owner_signoff")
        self.assertEqual(report_pending["blocking_reasons"], [])
        for comp in ("pinned_clarity", "dated_krea"):
            comp_res = report_pending["comparator_results"][comp]
            self.assertEqual(comp_res["sample_size"], 30)
            self.assertAlmostEqual(comp_res["win_rate"], 0.6667, places=4)
            self.assertAlmostEqual(comp_res["preference_plus_ties_rate"], 0.8333, places=4)
            self.assertTrue(comp_res["passed_thresholds"])

        approved_sub = _make_complete_submission(owner_status="approved")
        report_approved = evaluate_held_out_acceptance(approved_sub)
        self.assertTrue(report_approved["quantitative_gates_passed"])
        self.assertEqual(report_approved["overall_status"], "accepted")

    def test_critical_defect_split_contamination_and_category_drop_fail_closed(self) -> None:
        defect_sub = _make_complete_submission(
            owner_status="approved", include_critical_defect=True
        )
        defect_report = evaluate_held_out_acceptance(defect_sub)
        self.assertFalse(defect_report["quantitative_gates_passed"])
        self.assertEqual(defect_report["overall_status"], "failed")
        self.assertIn("critical_fidelity_defects_present", defect_report["blocking_reasons"])
        self.assertEqual(defect_report["critical_defect_count"], 1)

        contam_sub = _make_complete_submission(
            owner_status="approved", contaminate_split=True
        )
        contam_report = evaluate_held_out_acceptance(contam_sub)
        self.assertFalse(contam_report["quantitative_gates_passed"])
        self.assertEqual(contam_report["overall_status"], "failed")
        self.assertIn("split_contamination_detected", contam_report["blocking_reasons"])
        self.assertEqual(
            contam_report["calibration"]["split_contamination_ids"], ["portrait-01"]
        )

        cat_sub = _make_complete_submission(
            owner_status="approved", low_category="textile"
        )
        cat_report = evaluate_held_out_acceptance(cat_sub)
        self.assertFalse(cat_report["quantitative_gates_passed"])
        self.assertEqual(cat_report["overall_status"], "failed")
        self.assertIn("category_threshold_not_met", cat_report["blocking_reasons"])
        self.assertIn("textile", cat_report["category_failures"])

    def test_cli_exit_codes_for_signoff_and_incomplete_evidence(self) -> None:
        script = REPO_ROOT / "scripts" / "evaluate-quality-acceptance.py"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pending_path = root / "pending.json"
            pending_path.write_text(
                json.dumps(_make_complete_submission(owner_status="pending")),
                encoding="utf-8",
            )
            out_path = root / "report.json"

            proc_ok = subprocess.run(
                [sys.executable, str(script), str(pending_path), "--output", str(out_path)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(proc_ok.returncode, 0, msg=proc_ok.stderr)
            saved = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["overall_status"], "awaiting_owner_signoff")

            proc_strict = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    str(pending_path),
                    "--require-owner-signoff",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(proc_strict.returncode, 2)


if __name__ == "__main__":
    unittest.main()
