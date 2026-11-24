#!/usr/bin/env python3
"""Opt-in Context.dev public research capture. No effect on Fidelis inference.

Only user-approved public model/dataset pages are accepted. No image downloads.
"""
from __future__ import annotations

import argparse
import ipaddress
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

API = "https://api.context.dev/v1/web/scrape"
CACHE_MS = 86_400_000
SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "name": {"type": ["string", "null"]},
        "version": {"type": ["string", "null"]},
        "kind": {"type": ["string", "null"]},
        "purpose": {"type": ["string", "null"]},
        "license": {"type": ["string", "null"]},
        "license_url": {"type": ["string", "null"]},
        "hardware_requirements": {"type": ["string", "null"]},
        "apple_silicon_support": {"type": ["string", "null"]},
        "cpu_support": {"type": ["string", "null"]},
        "implementation_url": {"type": ["string", "null"]},
        "dataset_url": {"type": ["string", "null"]},
        "limitations": {"type": ["string", "null"]},
        "reported_benchmarks": {
            "type": "array", "items": {
                "type": "object", "additionalProperties": False,
                "properties": {
                    "metric": {"type": ["string", "null"]},
                    "value": {"type": ["string", "null"]},
                    "evaluation_dataset": {"type": ["string", "null"]},
                    "source_excerpt": {"type": ["string", "null"]},
                },
            },
        },
    },
}
INSTRUCTIONS = (
    "Extract only factual statements explicitly present on this public model or dataset page. "
    "Do not infer hardware or commercial rights from a model name. Missing fields are null or []. "
    "Publisher benchmark scores are third-party claims, not locally reproduced measurements."
)


def public_url(url: str) -> str:
    parts = urlsplit(url)
    host = (parts.hostname or "").lower().rstrip(".")
    if parts.scheme not in {"http", "https"} or not host or parts.username or parts.password:
        raise ValueError("only public HTTP(S) pages without URL credentials are allowed")
    if host in {"localhost", "localhost.localdomain"} or host.endswith((".local", ".internal", ".localhost", ".test")):
        raise ValueError("internal URL refused")
    try:
        ip = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        if "." not in host:
            raise ValueError("public hostname required")
    else:
        if not ip.is_global:
            raise ValueError("internal IP refused")
    if parts.port not in (None, 80, 443):
        raise ValueError("nonstandard URL port refused")
    return url


def scrape(url: str, *, api_key: str, include_images: bool = False,
           highlights: bool = False, zdr: bool = False, freshness_ms: int = CACHE_MS,
           request_fn=urlopen) -> dict:
    public_url(url)
    if not api_key:
        raise ValueError("CONTEXT_DEV_API_KEY not configured")
    if zdr and highlights:
        raise ValueError("highlights are incompatible with ZDR")
    if not 0 <= freshness_ms <= 31_536_000_000:
        raise ValueError("invalid cache freshness")
    formats = {"json": True, "markdown": True}
    if include_images:
        formats["images"] = True
    if highlights:
        formats["highlights"] = True
    payload = {
        "url": url, "formats": formats, "maxAgeMs": freshness_ms,
        "timeoutOpts": {"milliseconds": 20000},
        "zdr": "enabled" if zdr else "disabled",
        "jsonParams": {"schema": SCHEMA, "instructions": INSTRUCTIONS},
    }
    if highlights:
        payload["highlightsParams"] = {
            "query": "Explicit hardware support, license restrictions and reported evaluation results",
            "maxCharacters": 2000,
        }
    request = Request(API, method="POST",
                      data=json.dumps(payload).encode("utf-8"),
                      headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})
    start = time.monotonic()
    for attempt in range(2):
        remaining = 25.0 - (time.monotonic() - start)
        if remaining <= 0:
            raise RuntimeError("Context.dev request budget exhausted")
        try:
            with request_fn(request, timeout=min(20.0, remaining)) as response:
                raw = json.loads(response.read(4_000_000))
            if not isinstance(raw, dict):
                raise RuntimeError("invalid Context.dev response")
            outputs = {}
            for name in ("json", "markdown", "images", "highlights"):
                item = raw.get(name)
                if not isinstance(item, dict):
                    item = {"requested": name in formats, "success": False if name in formats else None, "data": None}
                outputs[name] = {
                    "requested": bool(item.get("requested")), "success": item.get("success"),
                    "error_code": item.get("error_code"), "message": item.get("message"),
                    "data": item.get("data") if item.get("success") is True else None,
                }
            parsed = outputs["json"]["data"] if isinstance(outputs["json"]["data"], dict) else {}
            return {
                "source_url": url,
                "final_url": raw.get("url", url),
                "retrieved_at": datetime.now(UTC).isoformat(),
                "request_id": raw.get("request_id"),
                "is_partial": bool(raw.get("isPartial")) or any(
                    x["success"] is False for x in outputs.values() if x["requested"]
                ),
                "formats": outputs,
                "extracted": parsed,
                # No rights are granted by a model card, repo link, or scrape.
                "license_review": "pending",
                "rights_cleared_for_benchmark": False,
                "publisher_results_locally_verified": False,
                "candidate_status": "pending_review",
            }
        except HTTPError as exc:
            if exc.code in {408, 409, 429, 500, 502, 503, 504} and attempt == 0:
                continue
            raise RuntimeError(f"Context.dev HTTP {exc.code}") from exc
        except (URLError, TimeoutError) as exc:
            if attempt == 0:
                continue
            raise RuntimeError(f"Context.dev connection failed: {type(exc).__name__}") from exc
    raise RuntimeError("Context.dev request failed")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", help="explicitly approved public model/dataset URL")
    parser.add_argument("--kind", choices=("model", "dataset"), default="model")
    parser.add_argument("--images", action="store_true", help="record image metadata for dataset pages only")
    parser.add_argument("--highlights", action="store_true", help="extra extraction cost")
    parser.add_argument("--zdr", action="store_true", help="requires account ZDR support")
    parser.add_argument("--fresh", action="store_true", help="bypass cached data (costs credits)")
    parser.add_argument("--out", default=".cache/contextdev-research.jsonl")
    args = parser.parse_args(argv)
    if args.images and args.kind != "dataset":
        parser.error("--images is allowed for --kind dataset only")
    key = os.environ.get("CONTEXT_DEV_API_KEY") or os.environ.get("CONTEXT_API_KEY", "")
    result = scrape(args.url, api_key=key, include_images=args.images, highlights=args.highlights,
                    zdr=args.zdr, freshness_ms=0 if args.fresh else CACHE_MS)
    result["research_kind"] = args.kind
    out = Path(args.out).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(result, ensure_ascii=False) + "\n")
    print(json.dumps({"source_url": result["source_url"], "is_partial": result["is_partial"],
                      "license_review": "pending", "saved_to": str(out)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
