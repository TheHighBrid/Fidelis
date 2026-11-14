#!/usr/bin/env python3
"""CLI for resumable, bounded production batches with persisted per-item recipes."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fidelis.postprocess.regions import PROFILES
from fidelis.studio.batch import BatchItemContext, BatchRunner

SUPPORTED_INPUT_SUFFIXES = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp"}


def _discover_inputs(input_dir: Path) -> list[Path]:
    if not input_dir.is_dir():
        raise FileNotFoundError(f"Input directory not found: {input_dir}")
    files = sorted(
        p for p in input_dir.iterdir()
        if p.is_file() and p.suffix.lower() in SUPPORTED_INPUT_SUFFIXES
    )
    if not files:
        raise ValueError(f"No supported images found in {input_dir}")
    return files


def _run_offline_handler(ctx: BatchItemContext) -> dict:
    src = Path(ctx.item["source_path"])
    handler = ctx.item["recipe"]["handler"]
    scale = int(ctx.item["recipe"].get("scale", 1))
    with Image.open(src) as im:
        im.load()
        if handler == "packshot_verify":
            if im.mode not in ("RGB", "RGBA"):
                raise ValueError(f"Unsupported mode {im.mode!r} in packshot_verify")
            shutil.copyfile(src, ctx.temp_output_path)
            return {"output_path": str(ctx.temp_output_path), "actual_cost_usd": 0.0}
        if handler == "deterministic_bicubic":
            rgb = im.convert("RGB")
            arr = np.array(rgb.resize((rgb.width * scale, rgb.height * scale), Image.Resampling.BICUBIC))
            Image.fromarray(arr).save(ctx.temp_output_path, format="PNG")
            return {"output_path": str(ctx.temp_output_path), "actual_cost_usd": 0.0}
    raise ValueError(f"Unsupported offline handler {handler!r}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    enq = sub.add_parser("enqueue", help="Persist per-image recipes before execution")
    enq.add_argument("--batch-dir", type=Path, required=True)
    enq.add_argument("--input-dir", type=Path, required=True)
    enq.add_argument("--output-dir", type=Path, required=True)
    enq.add_argument("--profile", choices=sorted(PROFILES), default="packshot_strict")
    enq.add_argument("--handler", choices=("packshot_verify", "deterministic_bicubic"), default="packshot_verify")
    enq.add_argument("--scale", type=int, default=1)
    enq.add_argument("--max-workers", type=int, default=2)
    enq.add_argument("--disk-budget-mib", type=int, default=2048)
    enq.add_argument("--cost-budget-usd", type=float, default=None)

    run = sub.add_parser("run", help="Run pending/interrupted items cleanly with resume safety")
    run.add_argument("--batch-dir", type=Path, required=True)
    run.add_argument("--max-workers", type=int, default=2)
    run.add_argument("--disk-budget-mib", type=int, default=2048)
    run.add_argument("--max-retries", type=int, default=2)
    run.add_argument("--cost-budget-usd", type=float, default=None)
    run.add_argument("--retry-failed", action="store_true")

    st = sub.add_parser("status", help="Inspect persisted batch status without lock contention")
    st.add_argument("--batch-dir", type=Path, required=True)

    args = parser.parse_args()
    try:
        if args.command == "enqueue":
            if not 1 <= args.scale <= 4:
                raise ValueError("scale must be in [1, 4]")
            inputs = _discover_inputs(args.input_dir)
            args.output_dir.mkdir(parents=True, exist_ok=True)
            entries = [
                {
                    "source_path": str(p),
                    "output_path": str(args.output_dir / f"{p.stem}.png"),
                    "recipe": {
                        "profile": args.profile,
                        "handler": args.handler,
                        "scale": args.scale,
                    },
                    "estimated_cost_usd": 0.0,
                }
                for p in inputs
            ]
            with BatchRunner(
                args.batch_dir,
                max_workers=args.max_workers,
                disk_budget_bytes=args.disk_budget_mib * 1024 * 1024,
                cost_budget_usd=args.cost_budget_usd,
            ) as runner:
                summary = runner.enqueue(entries)
                print(json.dumps({**summary, "status": runner.status()}, indent=2))
        elif args.command == "run":
            with BatchRunner(
                args.batch_dir,
                max_workers=args.max_workers,
                disk_budget_bytes=args.disk_budget_mib * 1024 * 1024,
                max_retries=args.max_retries,
                cost_budget_usd=args.cost_budget_usd,
            ) as runner:
                summary = runner.run(_run_offline_handler, retry_failed=args.retry_failed)
                print(json.dumps(summary, indent=2))
        else:
            runner = BatchRunner(args.batch_dir, read_only=True)
            try:
                print(json.dumps(runner.status(), indent=2))
            finally:
                runner.close()
    except (ValueError, OSError, RuntimeError) as error:
        parser.exit(2, f"batch-run: {error}\n")


if __name__ == "__main__":
    main()
