#!/usr/bin/env python3
"""Melato fabric, stitching, and hardware model-vs-4x-bicubic audition CLI."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import subprocess
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
from fidelis.eval.source_split_preflight import collect_source_split_index
from fidelis.studio.audition import (
    ManifestLoadOptions,
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


def _automated_gate_flags(cases: list[dict[str, Any]]) -> dict[str, bool]:
    if not cases:
        return {
            "interior_texture_passed": False,
            "oversharpen_restraint_passed": False,
            "fabric_weave_passed": False,
            "hardware_seam_passed": False,
        }
    return {
        "interior_texture_passed": all(
            bool(c.get("detail_metrics", {}).get("interior_texture_passed", False)) for c in cases
        ),
        "oversharpen_restraint_passed": all(
            bool(c.get("detail_metrics", {}).get("oversharpen_restraint_passed", False)) for c in cases
        ),
        "fabric_weave_passed": all(
            bool(c.get("detail_metrics", {}).get("fabric_weave_passed", True)) for c in cases
        ),
        "hardware_seam_passed": all(
            bool(c.get("detail_metrics", {}).get("hardware_seam_passed", True)) for c in cases
        ),
    }


def _build_acceptance_payload(
    report: dict[str, Any],
    protocol: dict[str, Any],
    receipt: dict[str, Any],
    *,
    manifest_paths: list[Path] | None = None,
) -> dict[str, Any]:
    cases = report.get("cases", [])
    cal_cases = [c for c in cases if c.get("split") == "calibration"]
    cal_case_hashes = {
        c["id"]: c["source_sha256"]
        for c in cal_cases
        if isinstance(c.get("source_sha256"), str) and c["source_sha256"]
    }
    submission = {
        "protocol_id": protocol.get("id", "melato-fabric-hardware-v1"),
        "reproducibility_receipt": receipt,
        "calibration_summary": {
            "recipe_frozen": False,
            "case_ids": [c["id"] for c in cal_cases],
            "source_sha256s": sorted(set(cal_case_hashes.values())),
            "case_source_hashes": cal_case_hashes,
        },
        "automated_metrics": _automated_gate_flags(cases),
        "ballots": [],
    }
    return evaluate_held_out_acceptance(
        submission,
        thresholds=AcceptanceThresholds(require_automated_detail_gates=True),
        manifest_paths=manifest_paths or None,
    )


def _case_source_sha256(case: dict[str, Any], asset_root: Path) -> str | None:
    declared = case.get("source_sha256")
    if isinstance(declared, str) and re.fullmatch(r"[0-9a-fA-F]{64}", declared):
        return declared.lower()
    src = case.get("source_path")
    if not src:
        return None
    src_path = Path(str(src))
    if not src_path.is_absolute():
        src_path = asset_root / src_path
    if not src_path.is_file():
        return None
    digest = hashlib.sha256()
    with src_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _check_selected_case_conflicts(
    cases: list[dict[str, Any]],
    index: dict[str, Any],
    asset_root: Path,
) -> None:
    conflict_shas = set(index["conflict_shas"])
    conflict_ids = {
        str(alias.get("id"))
        for group in index["report"]["conflicts"]
        for alias in group.get("aliases", ())
    }
    for case in cases:
        cid = str(case.get("id", ""))
        case_sha = _case_source_sha256(case, asset_root) or index["sha_by_id"].get(cid)
        if cid in conflict_ids or (case_sha is not None and case_sha in conflict_shas):
            raise ValueError(
                f"Selected case {cid!r} participates in a cross-split source-SHA conflict"
            )


def _preflight_case_split_isolation(
    cases: list[dict[str, Any]],
    manifest_paths: list[Path],
    *,
    asset_root: Path,
    enforce_passed: bool,
) -> dict[str, Any]:
    index = collect_source_split_index(manifest_paths)
    report = index["report"]
    if report["errors"] or index["id_hash_conflicts"]:
        raise ValueError(
            "Source split preflight failed due to invalid or conflicting manifest records"
        )
    if enforce_passed and not report["passed"]:
        raise ValueError(
            f"Source split isolation preflight status={report['status']!r} "
            f"(conflicts={report['summary']['conflict_count']}, "
            f"unknown_hashes={report['summary']['unknown_hash_count']})"
        )
    _check_selected_case_conflicts(cases, index, asset_root)
    return report


def _diagnostic_receipt(protocol_path: Path, manifest_path: Path | None) -> dict[str, Any]:
    """Capture actual inputs without treating a diagnostic manifest as a corpus lock."""
    repo = Path(__file__).resolve().parents[1]
    base_sha = None
    dirty = None
    try:
        base_sha = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo, check=True,
            capture_output=True, text=True, timeout=5,
        ).stdout.strip()
        dirty = bool(subprocess.run(
            ["git", "status", "--porcelain"], cwd=repo, check=True,
            capture_output=True, text=True, timeout=5,
        ).stdout.strip())
    except (OSError, subprocess.SubprocessError):
        pass
    return {
        "code_sha": base_sha if dirty is False else None,
        "code_base_sha": base_sha,
        "working_tree_dirty": dirty,
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "corpus_lock_sha256": None,
        "source_manifest_sha256": (
            hashlib.sha256(manifest_path.read_bytes()).hexdigest() if manifest_path else None
        ),
        "calibration_recipe_sha256": hashlib.sha256(protocol_path.read_bytes()).hexdigest(),
        "runtime_versions": {"python": platform.python_version()},
        "model_weight_hashes": {},
        "colour_path": "sRGB_linear_blend",
        "evidence_scope": "unfrozen_diagnostic_no_human_review",
    }


def _measured_weight_hashes(model: dict[str, Any]) -> dict[str, str]:
    value = model.get("weights_sha256")
    if isinstance(value, str) and re.fullmatch(r"[0-9a-fA-F]{64}", value):
        return {model.get("model_id", "candidate"): value.lower()}
    return {}


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
        "--torch-device",
        default="cpu",
        help="Device for --backend torch_spandrel (e.g. cpu, mps, cuda, auto).",
    )
    parser.add_argument(
        "--tile-core",
        type=int,
        default=None,
        help="Optional core tile size in source pixels for --backend torch_spandrel.",
    )
    parser.add_argument(
        "--tile-context",
        type=int,
        default=32,
        help="Optional overlap context in source pixels for tiled --backend torch_spandrel (default: 32).",
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
    parser.add_argument(
        "--raw-checkpoint-dir",
        type=Path,
        default=None,
        help="Persist raw model output and bicubic base .npy checkpoints per case before texture guarding.",
    )
    parser.add_argument(
        "--replay-checkpoint-dir",
        type=Path,
        default=None,
        help="Replay verified raw checkpoints from this directory without loading or calling an inference backend.",
    )
    parser.add_argument(
        "--split-preflight-manifest",
        type=Path,
        action="append",
        default=[],
        help="Additional manifest JSON path(s) checked for source-SHA cross-split aliases before running.",
    )
    parser.add_argument(
        "--enforce-split-isolation",
        action="store_true",
        help="Fail closed unless source-SHA split preflight across supplied manifests passes with zero conflicts or unknowns.",
    )
    return parser


def _resolve_cli_cases(
    args: argparse.Namespace,
    protocol: dict[str, Any],
    protocol_path: Path,
    scale: int,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None, str]:
    if args.smoke:
        smoke = protocol.get("smoke_fixture")
        if not isinstance(smoke, dict):
            raise ValueError(f"Protocol missing 'smoke_fixture': {protocol_path}")
        return [_normalize_case(smoke, scale=scale)], None, "held_out"
    if args.manifest is not None:
        manifest = _load_json(args.manifest)
        default_case_split = (
            "calibration" if isinstance(manifest, dict) and "assets" in manifest else "held_out"
        )
        cases, manifest_resolution = load_audition_cases_from_manifest(
            manifest,
            options=ManifestLoadOptions(
                scale=scale,
                asset_root=args.root,
                master_root=args.master_root,
                split=args.split,
                case_ids=args.select_id,
                skip_missing=args.skip_missing,
                exclude_synthetic=not args.include_synthetic,
                default_split=default_case_split,
            ),
        )
        default_blind_split = (
            args.split if args.split and args.split != "all" else default_case_split
        )
        return cases, manifest_resolution, default_blind_split
    return (
        [_build_single_image_case(args.image, case_id=args.case_id, rois_path=args.rois, scale=scale)],
        None,
        "held_out",
    )


def _run_split_preflight_if_requested(
    args: argparse.Namespace,
    cases: list[dict[str, Any]],
) -> tuple[list[Path], dict[str, Any] | None]:
    if not args.split_preflight_manifest and not args.enforce_split_isolation:
        return [], None
    preflight_manifests: list[Path] = []
    if args.manifest is not None:
        preflight_manifests.append(args.manifest)
    preflight_manifests.extend(args.split_preflight_manifest)
    split_preflight_report = _preflight_case_split_isolation(
        cases,
        preflight_manifests,
        asset_root=args.root,
        enforce_passed=args.enforce_split_isolation,
    )
    return preflight_manifests, split_preflight_report


def _create_cli_runner(args: argparse.Namespace):
    if args.replay_checkpoint_dir is not None:
        return None
    runner_kwargs: dict[str, Any] = {}
    if args.imported_dir is not None:
        runner_kwargs["imported_dir"] = args.imported_dir
    if args.weights is not None:
        runner_kwargs["weights_path"] = args.weights
    if args.model_id is not None:
        runner_kwargs["model_id"] = args.model_id
    if args.backend == "torch_spandrel":
        runner_kwargs["device"] = args.torch_device
        if args.tile_core is not None:
            runner_kwargs["tile_core"] = args.tile_core
        runner_kwargs["tile_context"] = args.tile_context
    if args.backend in ("realesrgan_ncnn", "hybrid"):
        runner_kwargs["detail_blend_weight"] = args.detail_blend_weight
    if args.backend == "hybrid":
        runner_kwargs["address"] = args.comfy_address
    return create_restoration_runner(args.backend, **runner_kwargs)


def _write_acceptance_outputs(
    args: argparse.Namespace,
    report: dict[str, Any],
    protocol: dict[str, Any],
    receipt: dict[str, Any],
    preflight_manifests: list[Path],
    split_preflight_report: dict[str, Any] | None,
    out_summary: dict[str, Any],
) -> None:
    model = report.get("model", {})
    receipt["model_weight_hashes"] = _measured_weight_hashes(model)
    receipt["seed_policy"] = f"blind_seed={args.blind_seed}"
    receipt["source_case_hashes"] = {
        c["id"]: c["source_sha256"]
        for c in report.get("cases", [])
        if c.get("source_sha256")
    }
    if split_preflight_report is not None:
        receipt["source_split_preflight"] = split_preflight_report["summary"]
    receipt_path = args.output_dir / "audition_receipt.json"
    _write_json(receipt_path, receipt)
    acceptance = _build_acceptance_payload(
        report,
        protocol,
        receipt,
        manifest_paths=preflight_manifests or None,
    )
    acceptance_path = args.output_dir / "acceptance_summary.json"
    _write_json(acceptance_path, acceptance)
    out_summary["acceptance_summary"] = str(acceptance_path)
    out_summary["acceptance_status"] = acceptance.get("overall_status")
    out_summary["audition_receipt"] = str(receipt_path)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        protocol_path = args.protocol if args.protocol.is_absolute() else (args.root / args.protocol)
        protocol = _load_json(protocol_path)
        receipt = _diagnostic_receipt(protocol_path, args.manifest)
        scale = int(protocol.get("scale", 4))

        cases, manifest_resolution, default_blind_split = _resolve_cli_cases(
            args, protocol, protocol_path, scale
        )
        blind_split = args.blind_split if args.blind_split is not None else default_blind_split
        preflight_manifests, split_preflight_report = _run_split_preflight_if_requested(args, cases)
        runner = _create_cli_runner(args)

        report = run_model_vs_bicubic_audition(
            cases,
            runner,
            output_dir=args.output_dir,
            blind_seed=args.blind_seed,
            apply_texture_guard=not args.no_texture_guard,
            generate_html=not args.no_html,
            asset_root=args.root,
            blind_split=blind_split,
            raw_checkpoint_dir=args.raw_checkpoint_dir,
            replay_checkpoint_dir=args.replay_checkpoint_dir,
            protocol_sha256=receipt["calibration_recipe_sha256"],
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
            _write_acceptance_outputs(
                args, report, protocol, receipt, preflight_manifests, split_preflight_report, out_summary
            )
        if split_preflight_report is not None:
            out_summary["source_split_preflight"] = split_preflight_report["summary"]

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
