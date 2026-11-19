"""Structural regressions for Bot 05 photographic restoration protocol."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "photographic_protocol"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from fidelis.eval.photographic_protocol import (  # noqa: E402
    DefectCode,
    ProtocolVerdict,
    evaluate_restoration_pair,
    list_rubrics,
)
from fidelis.eval.texture_eval_hooks import (  # noqa: E402
    TextureEvalRequest,
    evaluate_texture_candidate,
    hook_contract,
    write_protocol_receipt,
)


class PhotographicProtocolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        required = [
            "skin_base.png",
            "skin_plastic.png",
            "skin_good.png",
            "textile_base.png",
            "textile_hallucinated.png",
            "product_base.png",
            "product_invented.png",
            "lettering_base.png",
            "lettering_mutated.png",
            "lettering_good.png",
            "hair_base.png",
            "hair_exaggerated.png",
        ]
        missing = [name for name in required if not (FIXTURES / name).is_file()]
        if missing:
            raise unittest.SkipTest(f"Missing protocol fixtures: {missing}")

    def test_rubrics_cover_five_categories_and_reject_sharpness_proxy(self) -> None:
        rubrics = list_rubrics()
        cats = {r["category"] for r in rubrics}
        self.assertEqual(cats, {"skin", "hair", "textiles", "products", "lettering"})
        self.assertTrue(any(r["criterion_id"] == "no_sharpness_proxy" for r in rubrics))
        statements = " ".join(r["statement"].lower() for r in rubrics)
        self.assertIn("sharpness", statements)

    def test_plastic_skin_fails_even_if_edges_look_crisp(self) -> None:
        report = evaluate_restoration_pair(
            FIXTURES / "skin_base.png",
            FIXTURES / "skin_plastic.png",
            category="skin",
            case_id="synthetic_skin_plastic",
        )
        codes = {d.code for d in report.defects}
        self.assertEqual(report.verdict, ProtocolVerdict.FAIL)
        self.assertTrue(
            DefectCode.PLASTIC_SKIN in codes or DefectCode.SHARPNESS_WITHOUT_RESTORATION in codes,
            msg=report.to_dict(),
        )
        self.assertFalse(report.is_production_corpus)

    def test_mild_skin_candidate_can_pass_protocol(self) -> None:
        report = evaluate_restoration_pair(
            FIXTURES / "skin_base.png",
            FIXTURES / "skin_good.png",
            category="skin",
            case_id="synthetic_skin_good",
        )
        self.assertEqual(report.verdict, ProtocolVerdict.PASS, msg=report.to_dict())


    def test_exaggerated_hair_fails(self) -> None:
        report = evaluate_restoration_pair(
            FIXTURES / "hair_base.png",
            FIXTURES / "hair_exaggerated.png",
            category="hair",
        )
        codes = {d.code for d in report.defects}
        self.assertEqual(report.verdict, ProtocolVerdict.FAIL)
        self.assertTrue(
            DefectCode.EXAGGERATED_TEXTURE in codes
            or DefectCode.SHARPNESS_WITHOUT_RESTORATION in codes,
            msg=report.to_dict(),
        )

    def test_textile_hallucination_fails(self) -> None:
        report = evaluate_restoration_pair(
            FIXTURES / "textile_base.png",
            FIXTURES / "textile_hallucinated.png",
            category="textiles",
        )
        codes = {d.code for d in report.defects}
        self.assertEqual(report.verdict, ProtocolVerdict.FAIL)
        self.assertTrue(
            DefectCode.WEAVE_HALLUCINATION in codes
            or DefectCode.EXAGGERATED_TEXTURE in codes
            or DefectCode.SHARPNESS_WITHOUT_RESTORATION in codes,
            msg=report.to_dict(),
        )

    def test_invented_product_detail_fails(self) -> None:
        report = evaluate_restoration_pair(
            FIXTURES / "product_base.png",
            FIXTURES / "product_invented.png",
            category="products",
        )
        codes = {d.code for d in report.defects}
        self.assertEqual(report.verdict, ProtocolVerdict.FAIL)
        self.assertIn(DefectCode.INVENTED_PRODUCT_DETAIL, codes, msg=report.to_dict())

    def test_lettering_mutation_fails_and_good_lettering_passes(self) -> None:
        bad = evaluate_restoration_pair(
            FIXTURES / "lettering_base.png",
            FIXTURES / "lettering_mutated.png",
            category="lettering",
        )
        good = evaluate_restoration_pair(
            FIXTURES / "lettering_base.png",
            FIXTURES / "lettering_good.png",
            category="lettering",
        )
        self.assertEqual(bad.verdict, ProtocolVerdict.FAIL, msg=bad.to_dict())
        self.assertIn(DefectCode.LETTERING_MUTATION, {d.code for d in bad.defects})
        self.assertEqual(good.verdict, ProtocolVerdict.PASS, msg=good.to_dict())

    def test_refuses_production_corpus_flag_on_synthetic_path(self) -> None:
        with self.assertRaises(ValueError):
            evaluate_restoration_pair(
                FIXTURES / "skin_base.png",
                FIXTURES / "skin_good.png",
                category="skin",
                is_production_corpus=True,
            )

    def test_bot04_hook_writes_receipt(self) -> None:
        contract = hook_contract()
        self.assertEqual(contract["consumer_lane"], "Bot 04 zero-cost texture restoration")
        self.assertIn("skin", contract["categories"])
        report = evaluate_texture_candidate(
            TextureEvalRequest(
                base_path=FIXTURES / "skin_base.png",
                candidate_path=FIXTURES / "skin_plastic.png",
                category="skin",
                case_id="bot04_hook_smoke",
                adapter_id="bot04.zero_cost.fixture",
            )
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = write_protocol_receipt(report, tmp)
            payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(payload["verdict"], "FAIL")
        self.assertEqual(payload["hook_contract_id"], "fidelis.bot05.texture_eval_hooks")
        self.assertFalse(payload["is_production_corpus"])

    def test_cli_emits_json_receipt(self) -> None:
        script = REPO_ROOT / "scripts" / "run-photographic-protocol.py"
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "receipt.json"
            proc = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "--base",
                    str(FIXTURES / "product_base.png"),
                    "--candidate",
                    str(FIXTURES / "product_invented.png"),
                    "--category",
                    "products",
                    "--json-out",
                    str(out),
                ],
                cwd=str(REPO_ROOT),
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(proc.returncode, 2, msg=proc.stdout + proc.stderr)
            payload = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(payload["verdict"], "FAIL")


if __name__ == "__main__":
    unittest.main()
