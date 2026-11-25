#!/usr/bin/env python3
"""Melato fabric, stitching, and hardware model-vs-4x-bicubic audition CLI."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fidelis.engine.restoration_runner import (
    BackendUnavailableError,
    DimensionMismatchError,
    create_restoration_runner,
)
from fidelis.eval.quality_acceptance import (
    AcceptanceThresholds,
    evaluate_held_out_acceptance,
)
from fidelis.studio.audition import (
    load_audition_cases_from_manifest,
    run_model_vs_bicubic_audition,
)


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _normalize_case(raw_case: dict[str, Any], *, scale: int) -> dict[str, Any]:
    case = dict(raw_case)
    if "source_path" not in case:
        source_obj = case.get("source")
        if isinstance(source_obj, dict) and source_obj.get("path"):
            case["source_path"] = source_obj["path"]
        else:
            raise KeyError(f"Case {case.get('id', '<unknown>')} missing 'source_path' or 'source.path'")
    case.setdefault("scale", scale)
    case.setdefault("roi_space", "source")
    case.setdefault("split", "held_out")
    case.setdefault("category", "model_apparel")
    return case


def _load_rois_file(path: Path) -> list[dict[str, Any]]:
    payload = _load_json(path)
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get("rois"), list):
        return payload["rois"]
    raise ValueError(f"ROI file must contain a JSON list or {{\"rois\": [...]}}: {path}")


def _build_single_image_case(
    image_path: Path,
    *,
    case_id: str,
    rois_path: Path | None,
    scale: int,
) -> dict[str, Any]:
    with Image.open(image_path) as img:
        w, h = img.size
    if rois_path is not None:
        rois = _load_rois_file(rois_path)
    else:
        margin_x = 0 if w < 4 else max(1, w // 10)
        margin_y = 0 if h < 4 else max(1, h // 10)
        roi_w = max(1, min(w - margin_x, w - 2 * margin_x))
        roi_h = max(1, min(h - margin_y, h - 2 * margin_y))
        rois = [
            {
                "id": "melato_fabric_default",
                "kind": "fabric",
                "policy": "texture_allowed",
                "override": None,
                "rect": [
                    margin_x,
                    margin_y,
                    roi_w,
                    roi_h,
                ],
            }
        ]
    return {
        "id": case_id,
        "role": "regression",
        "category": "model_apparel",
        "split": "held_out",
        "source_path": str(image_path),
        "target_dimensions": [w * scale, h * scale],
        "scale": scale,
        "roi_space": "source",
        "rois": rois,
    }


def _build_acceptance_payload(
    report: dict[str, Any],
    protocol: dict[str, Any],
) -> dict[str, Any]:
    cases = report.get("cases", [])
    all_texture = all(
        bool(c.get("detail_metrics", {}).get("interior_texture_passed", False))
        for c in cases
    )
    all_oversharpen = all(
        bool(c.get("detail_metrics", {}).get("oversharpen_restraint_passed", False))
        for c in cases
    )
    all_weave = all(
        bool(c.get("detail_metrics", {}).get("fabric_weave_passed", True))
        for c in cases
    )
    all_hw = all(
        bool(c.get("detail_metrics", {}).get("hardware_seam_passed", True))
        for c in cases
    )
    submission = {
        "protocol_id": protocol.get("id", "melato-fabric-hardware-v1"),
        "reproducibility_receipt": {
            "code_sha": "audition-melato-local",
            "corpus_lock_sha256": "unfrozen-melato-audition",
            "calibration_recipe_sha256": "melato-protocol-v1",
            "runtime_versions": {"python": "3"},
            "model_weight_hashes": {
                report.get("model", {}).get("model_id", "candidate"): "local"
            },
            "seed_policy": f"blind_seed={report.get('blind', {}).get('seed', report.get('blind_seed', 20261110))}",
            "colour_path": "sRGB_linear_blend",
        },
        "calibration_summary": {
            "recipe_frozen": True,
            "case_ids": [],
        },
        "automated_metrics": {
            "interior_texture_passed": all_texture if cases else False,
            "oversharpen_restraint_passed": all_oversharpen if cases else False,
            "fabric_weave_passed": all_weave if cases else False,
            "hardware_seam_passed": all_hw if cases else False,
        },
        "ballots": [],
    }
    return evaluate_held_out_acceptance(
        submission,
        thresholds=AcceptanceThresholds(require_automated_detail_gates=True),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run Melato fabric, stitching, and hardware model-vs-4x-bicubic audition."
    )
    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument(
        "--smoke",
        action="store_true",
        help="Run the built-in Melato smoke fixture from --protocol.",
    )
    source_group.add_argument(
        "--manifest",
        type=Path,
        help="Path to a Melato case manifest JSON (e.g. melato-corpus-template-v1.json).",
    )
    source_group.add_argument(
        "--image",
        type=Path,
        help="Path to a single operator-supplied Melato photograph.",
    )

    parser.add_argument(
        "--rois",
        type=Path,
        default=None,
        help="Optional ROI JSON file when using --image.",
    )
    parser.add_argument(
        "--case-id",
        default="melato-case",
        help="Case ID to assign when using --image (default: melato-case).",
    )
    parser.add_argument(
        "--protocol",
        type=Path,
        default=Path("config/benchmark/melato-protocol.json"),
        help="Path to Melato evaluation protocol JSON.",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="Asset root directory for resolving relative source paths.",
    )
    parser.add_argument(
        "--master-root",
        type=Path,
        default=None,
        help="Off-repo Melato master directory (e.g. ~/melato-corpus/fidelis) for manifest entries.",
    )
    parser.add_argument(
        "--split",
        default=None,
        help="Optional split filter when using --manifest (calibration, held_out, all).",
    )
    parser.add_argument(
        "--select-id",
        action="append",
        default=[],
        help="Restrict --manifest audition to specific case_id/asset_id values (repeatable).",
    )
    parser.add_argument(
        "--skip-missing",
        action="store_true",
        help="Skip manifest entries that are missing on disk, uncleared, or lack annotated bbox_norm.",
    )
    parser.add_argument(
        "--include-synthetic",
        action="store_true",
        help="Include synthetic/non-ground-truth manifest entries (excluded by default).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Directory where audition outputs, crops, and blind ballots are written.",
    )
    parser.add_argument(
        "--backend",
        choices=["bicubic", "imported", "onnxruntime", "torch_spandrel", "realesrgan_ncnn", "hybrid"],
        default="imported",
        help="Restoration backend to audition against 4x bicubic.",
    )
    parser.add_argument(
        "--detail-blend-weight",
        type=float,
        default=1.0,
        help="Optional detail blend weight in (0.0, 1.0] for realesrgan_ncnn / hybrid backends.",
    )
    parser.add_argument(
        "--comfy-address",
        default="http://127.0.0.1:8188",
        help="Loopback ComfyUI worker address for --backend hybrid.",
    )
    parser.add_argument(
        "--imported-dir",
        type=Path,
        default=None,
        help="Directory containing candidate 4x images for --backend imported.",
    )
    parser.add_argument(
        "--weights",
        type=Path,
        default=None,
        help="Model weights path for onnxruntime / torch_spandrel backends.",
    )
    parser.add_argument(
        "--model-id",
        default=None,
        help="Optional model identifier recorded in the audition report.",
    )
    parser.add_argument(
        "--no-texture-guard",
        action="store_true",
        help="Disable ROI texture guard composition (for ablation/baseline checks).",
    )
    parser.add_argument(
        "--no-html",
        action="store_true",
        help="Skip generating audition_report.html.",
    )
    parser.add_argument(
        "--blind-seed",
        type=int,
        default=20261110,
        help="Deterministic seed for blind pairwise ballot generation.",
    )
    parser.add_argument(
        "--blind-split",
        default=None,
        help="Split filter for blind pairwise ballot generation (default: held_out, or --split / manifest split).",
    )
    parser.add_argument(
        "--evaluate-acceptance",
        action="store_true",
        help="Evaluate automated detail gates via evaluate_held_out_acceptance and write acceptance_summary.json.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        protocol_path = args.protocol if args.protocol.is_absolute() else (args.root / args.protocol)
        protocol = _load_json(protocol_path)
        scale = int(protocol.get("scale", 4))

        manifest_resolution: dict[str, Any] | None = None
        if args.smoke:
            smoke = protocol.get("smoke_fixture")
            if not isinstance(smoke, dict):
                raise ValueError(f"Protocol missing 'smoke_fixture': {protocol_path}")
            cases = [_normalize_case(smoke, scale=scale)]
            default_blind_split = "held_out"
        elif args.manifest is not None:
            manifest = _load_json(args.manifest)
            default_case_split = (
                "calibration" if isinstance(manifest, dict) and "assets" in manifest else "held_out"
            )
            cases, manifest_resolution = load_audition_cases_from_manifest(
                manifest,
                scale=scale,
                asset_root=args.root,
                master_root=args.master_root,
                split=args.split,
                case_ids=args.select_id,
                skip_missing=args.skip_missing,
                exclude_synthetic=not args.include_synthetic,
                default_split=default_case_split,
            )
            default_blind_split = (
                args.split if args.split and args.split != "all" else default_case_split
            )
        else:
            cases = [
                _build_single_image_case(
                    args.image,
                    case_id=args.case_id,
                    rois_path=args.rois,
                    scale=scale,
                )
            ]
            default_blind_split = "held_out"

        blind_split = args.blind_split if args.blind_split is not None else default_blind_split

        runner_kwargs: dict[str, Any] = {}
        if args.imported_dir is not None:
            runner_kwargs["imported_dir"] = args.imported_dir
        if args.weights is not None:
            runner_kwargs["weights_path"] = args.weights
        if args.model_id is not None:
            runner_kwargs["model_id"] = args.model_id
        if args.backend in ("realesrgan_ncnn", "hybrid"):
            runner_kwargs["detail_blend_weight"] = args.detail_blend_weight
        if args.backend == "hybrid":
            runner_kwargs["address"] = args.comfy_address

        runner = create_restoration_runner(args.backend, **runner_kwargs)
        report = run_model_vs_bicubic_audition(
            cases,
            runner,
            output_dir=args.output_dir,
            blind_seed=args.blind_seed,
            apply_texture_guard=not args.no_texture_guard,
            generate_html=not args.no_html,
            asset_root=args.root,
            blind_split=blind_split,
        )

        blind_info = report.get("blind", {})
        out_summary: dict[str, Any] = {
            "protocol_id": protocol.get("id"),
            "report": report["report_json_path"],
            "html": report.get("report_html_path"),
            "blind_ballot": blind_info.get("ballot_path"),
            "blind_answer_key": blind_info.get("answer_key_path"),
            "summary": report["summary"],
        }
        if manifest_resolution is not None:
            out_summary["manifest_resolution"] = manifest_resolution

        if args.evaluate_acceptance:
            acceptance = _build_acceptance_payload(report, protocol)
            acceptance_path = args.output_dir / "acceptance_summary.json"
            _write_json(acceptance_path, acceptance)
            out_summary["acceptance_summary"] = str(acceptance_path)
            out_summary["acceptance_status"] = acceptance.get("overall_status")

        print(json.dumps(out_summary, indent=2))
        return 0
    except (
        ValueError,
        TypeError,
        OSError,
        KeyError,
        BackendUnavailableError,
        DimensionMismatchError,
    ) as error:
        parser.exit(2, f"audition-melato: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
