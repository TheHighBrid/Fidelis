#!/usr/bin/env python3
"""Export saved, revision-pinned Studio masters sequentially without inference."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fidelis.studio.store import JobStore, sha256, write_rgb_png


def export_batch(store, recipe, output_dir, byte_budget):
    if not isinstance(recipe, list) or not 1 <= len(recipe) <= 1000:
        raise ValueError("Recipe must contain 1 to 1000 saved job revisions")
    names = set()
    required = {"job_id", "revision", "filename"}
    for item in recipe:
        if not isinstance(item, dict) or set(item) - {"depth"} != required:
            raise ValueError("Each entry requires job_id, revision and filename")
        depth = item.get("depth", 8)
        if type(depth) is not int or depth not in (8, 16):
            raise ValueError("Export depth must be 8 or 16")
        name = item["filename"]
        if (not isinstance(name, str) or not name.endswith(".png") or len(name) > 120
                or not all(c.isascii() and (c.isalnum() or c in "._-") for c in name)
                or name.startswith(".") or name.lower() in names):
            raise ValueError("Each filename must be a distinct, visible PNG basename")
        names.add(name.lower())
        if type(item["revision"]) is not int or item["revision"] < 1:
            raise ValueError("Each entry must pin a positive saved revision")
        if not isinstance(item["job_id"], str):
            raise ValueError("Job ID must be a string")

    output_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / ".fidelis-export.lock").open("ab") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return _export_locked(store, recipe, output_dir, byte_budget)


def _export_locked(store, recipe, output_dir, byte_budget):
    used = sum(path.stat().st_size for path in output_dir.iterdir()
               if path.is_file() and not path.is_symlink())
    # A terminated process may leave a staging directory behind.
    for directory in output_dir.glob(".fidelis-export-*"):
        if directory.is_dir() and not directory.is_symlink():
            used += sum(path.stat().st_size for path in directory.iterdir()
                        if path.is_file() and not path.is_symlink())
    results = []
    for item in recipe:
        depth = item.get("depth", 8)
        path = output_dir / item["filename"]
        receipt_path = path.with_suffix(".png.recipe.json")
        if path.is_symlink() or receipt_path.is_symlink():
            raise ValueError(f"Destination must not be a symlink: {path.name}")
        if receipt_path.exists():
            if receipt_path.stat().st_size > 4096:
                raise ValueError(f"Existing export receipt is too large: {path.name}")
            record = json.loads(receipt_path.read_text(encoding="utf-8"))
            if (not isinstance(record, dict) or not path.is_file() or any(record.get(key) != value for key, value in item.items() if key != "depth")
                    or record.get("depth", 8) != depth or record.get("schema_version") != 1
                    or record.get("output_sha256") != sha256(path)):
                raise ValueError(f"Existing export receipt does not match: {path.name}")
            results.append({**item, "status": "reused"})
            continue

        if path.exists() and not path.is_file():
            raise ValueError(f"Destination is not a file: {path.name}")
        with TemporaryDirectory(dir=output_dir, prefix=".fidelis-export-") as temp:
            pending = Path(temp) / "master.png"
            if depth == 16:
                opened = store.open_master16(item["job_id"], item["revision"])
            else:
                opened = store.open_array(item["job_id"], "master", expected_revision=item["revision"])
            with opened as master:
                try:
                    with pending.open("wb") as stream:
                        write_rgb_png(master, stream, max_bytes=byte_budget - used)
                        stream.flush()
                        os.fsync(stream.fileno())
                finally:
                    del master  # Release the mapped staging file before opening the next job.
            record = {"schema_version": 1, **item, "depth": depth, "output_sha256": sha256(pending),
                      "inference_executed": False, "provenance": "unsigned_execution_record"}
            receipt = Path(temp) / "receipt.json"
            receipt_bytes = (json.dumps(record, indent=2) + "\n").encode("utf-8")
            if used + pending.stat().st_size + len(receipt_bytes) > byte_budget:
                raise ValueError("Batch export exceeds the output directory budget")
            receipt.write_bytes(receipt_bytes)
            # The hard link publishes complete bytes and refuses to replace a file.
            try:
                os.link(pending, path)
                used += pending.stat().st_size
            except FileExistsError:
                if not path.is_file() or sha256(path) != record["output_sha256"]:
                    raise ValueError(f"Existing output differs: {path.name}")
            try:
                os.link(receipt, receipt_path)
                used += receipt.stat().st_size
            except FileExistsError:
                if receipt_path.read_bytes() != receipt_bytes:
                    raise ValueError(f"Existing export receipt differs: {path.name}")
        results.append({**item, "status": "exported"})
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("recipe", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--output-budget-mib", type=int, default=2048)
    args = parser.parse_args()
    try:
        if args.output_budget_mib < 1 or args.recipe.stat().st_size > 1024**2:
            raise ValueError("Set a positive output budget and use a recipe of at most 1 MiB")
        if not (args.workspace / "jobs.sqlite3").is_file():
            raise ValueError("Use an existing Studio workspace")
        recipe = json.loads(args.recipe.read_text(encoding="utf-8"))
        print(json.dumps(export_batch(JobStore(args.workspace), recipe, args.output_dir,
                                      args.output_budget_mib * 1024**2)))
    except (ValueError, OSError, KeyError) as error:
        parser.exit(2, f"export-studio-batch: {error}\n")


if __name__ == "__main__":
    main()
