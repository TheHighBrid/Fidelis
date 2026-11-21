"""Offline, fail-closed release declaration gate. Not an evidence verifier."""
import argparse
import json
from pathlib import Path


class ManifestError(ValueError):
    pass


def assess(manifest):
    if not isinstance(manifest, dict) or manifest.get("schema_version") != "fidelis.release_candidate.v1":
        raise ManifestError("Unsupported release candidate manifest")
    quality = manifest.get("quality_gate")
    operations = manifest.get("operational_gate")
    signoff = manifest.get("owner_release_signoff")
    if not all(isinstance(x, dict) for x in (quality, operations, signoff)):
        raise ManifestError("Missing release gate records")
    digest = quality.get("report_sha256")
    checks = {
        "merged_to_main": manifest.get("merged_to_main") is True,
        "quality_accepted": quality.get("overall_status") == "accepted"
            and isinstance(digest, str) and len(digest) == 64
            and all(c in "0123456789abcdefABCDEF" for c in digest),
        "live_worker_verified": operations.get("live_worker_verified") is True,
        "device_budgets_measured": operations.get("device_budgets_measured") is True,
        "upgrade_rollback_verified": operations.get("upgrade_rollback_verified") is True,
        "creative_signoff": signoff.get("status") == "approved"
            and bool(signoff.get("creative_owner")) and bool(signoff.get("signed_at")),
        "release_signoff": signoff.get("status") == "approved"
            and bool(signoff.get("release_owner")) and bool(signoff.get("signed_at")),
    }
    return {"ready": all(checks.values()), "checks": checks,
            "unmet": [key for key, passed in checks.items() if not passed],
            "evidence_level": "manifest_declarations_only"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args(argv)
    try:
        result = assess(json.loads(args.manifest.read_text(encoding="utf-8")))
    except (ManifestError, OSError, UnicodeError, json.JSONDecodeError) as error:
        parser.exit(2, f"Invalid release manifest: {error}\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
