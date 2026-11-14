#!/usr/bin/env python3
"""Run reproducible corpus comparators or score blind pairwise comparison ballots."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fidelis.eval.comparators import (
    CANONICAL_COMPARATORS,
    build_blind_pairwise_manifest,
    make_imported_output_runner,
    run_comparators,
    summarize_blind_reviews,
)


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="Run configured comparators on locked corpus or regression manifest")
    run_p.add_argument("manifest_or_lock", type=Path)
    run_p.add_argument("--root", type=Path, default=Path.cwd())
    run_p.add_argument("--output-dir", type=Path, required=True)
    run_p.add_argument("--protocol", type=Path, default=Path("config/benchmark/protocol-v1.json"))
    run_p.add_argument("--slots", type=Path, default=Path("config/benchmark/slots-v1.json"))
    run_p.add_argument(
        "--imported-dir",
        action="append",
        default=[],
        help="Optional comparator=DIR mapping for pre-rendered outputs",
    )
    run_p.add_argument("--allow-regression-manifest", action="store_true")
    run_p.add_argument("--blind-pair", nargs=2, metavar=("COMP_A", "COMP_B"), default=None)
    run_p.add_argument("--blind-split", default="held_out")

    score_p = sub.add_parser("summarize-blind", help="Score a reviewed blind pairwise ballot JSON")
    score_p.add_argument("ballot", type=Path)
    score_p.add_argument("answer_key", type=Path)
    score_p.add_argument("--subject", required=True)
    score_p.add_argument("--target", required=True)
    score_p.add_argument("--output", type=Path, default=None)

    args = parser.parse_args()
    try:
        if args.command == "run":
            doc = _load_json(args.manifest_or_lock)
            runners = {}
            for spec in args.imported_dir:
                if "=" not in spec:
                    raise ValueError(f"--imported-dir expects comparator=DIR, got {spec!r}")
                comp, dir_str = spec.split("=", 1)
                if comp not in CANONICAL_COMPARATORS:
                    raise ValueError(f"Unknown comparator {comp!r}")
                runners[comp] = make_imported_output_runner(comp, Path(dir_str))

            prot = _load_json(args.protocol) if args.allow_regression_manifest else None
            slots = _load_json(args.slots) if args.allow_regression_manifest else None
            report = run_comparators(
                doc,
                asset_root=args.root,
                output_dir=args.output_dir,
                runners=runners,
                protocol=prot,
                slots=slots,
                allow_regression_manifest=args.allow_regression_manifest,
            )
            report_path = args.output_dir / "comparison-report.json"
            _write_json(report_path, report)

            out = {"report": str(report_path), "case_count": report["case_count"], "comparators": report["comparators"]}
            if args.blind_pair:
                ballot, key_doc = build_blind_pairwise_manifest(
                    report, args.blind_pair[0], args.blind_pair[1], split=args.blind_split
                )
                ballot_path = args.output_dir / "blind-ballot.json"
                key_path = args.output_dir / "blind-answer-key.json"
                _write_json(ballot_path, ballot)
                _write_json(key_path, key_doc)
                out["blind_ballot"] = str(ballot_path)
                out["blind_answer_key"] = str(key_path)
            print(json.dumps(out, indent=2))
        else:
            summary = summarize_blind_reviews(
                _load_json(args.ballot),
                _load_json(args.answer_key),
                subject_comparator=args.subject,
                target_comparator=args.target,
            )
            if args.output is not None:
                _write_json(args.output, summary)
            print(json.dumps(summary, indent=2))
    except (ValueError, OSError, KeyError) as error:
        parser.exit(2, f"run-comparators: {error}\n")


if __name__ == "__main__":
    main()
