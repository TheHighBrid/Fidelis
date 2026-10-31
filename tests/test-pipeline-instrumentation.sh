#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"

python_bin="${PYTHON_BIN:-}"
if [[ -z "$python_bin" ]]; then
  if [[ -x "$repo_root/.venv/bin/python" ]]; then
    python_bin="$repo_root/.venv/bin/python"
  else
    python_bin="python3"
  fi
fi

printf "Testing Fidelis Pipeline Instrumentation & C2PA Provenance...\n"

out_dir="$(mktemp -d /tmp/fidelis_pipe_test_XXXXXX)"
trap 'rm -rf "$out_dir"' EXIT

manifest_out="$out_dir/manifest.json"
img_out="$out_dir/upscaled.png"

# Run instrumented upscaling via CLI
"$python_bin" "$repo_root/scripts/upscale.py" \
  "$repo_root/tests/fixtures/portrait_skin.png" \
  "$img_out" \
  --model realesrgan-x4plus \
  --tile-size 256 \
  --json-manifest "$manifest_out"

[[ -s "$img_out" ]] || { printf "Output image missing!\n" >&2; exit 1; }
[[ -s "$manifest_out" ]] || { printf "Manifest missing!\n" >&2; exit 1; }
[[ -s "$out_dir/upscaled.png.c2pa.json" ]] || { printf "C2PA sidecar manifest missing!\n" >&2; exit 1; }

# Verify JSON manifest fields
"$python_bin" -c '
import json, sys
with open(sys.argv[1]) as f:
    m = json.load(f)

in_dims = m["input_dimensions"]
out_dims = m["output_dimensions"]
fmt = m["input_format"]
prof = m["model_profile"]
ts = m["tile_size"]
c2pa = m["c2pa_status"]

assert in_dims == [256, 256], f"Bad input dims: {in_dims}"
assert out_dims == [1024, 1024], f"Bad output dims: {out_dims}"
assert fmt == "PNG", f"Bad format: {fmt}"
assert m["input_noise_level"] > 0, "Noise level must be positive"
assert prof == "realesrgan-x4plus", f"Bad profile: {prof}"
assert ts == 256, f"Bad tile size: {ts}"
assert m["vram_peak_mb"] > 0, "VRAM peak memory must be recorded"
assert m["processing_time_per_megapixel_ms"] > 0, "Time per megapixel must be positive"
assert len(m["output_sha256"]) == 64, "Output SHA256 must be 64-char hex"
assert c2pa == "verified", f"Bad C2PA status: {c2pa}"
assert m["exif_preserved"] is True, "EXIF preservation should be true"
assert m["zero_black_tiles"] is True, "Zero black tiles should be true"
span_count = len(m["spans"])
assert span_count >= 3, f"Expected at least 3 spans, got {span_count}"
print("Manifest telemetry verification passed successfully.")
' "$manifest_out"

# Test CLI integration: bin/fidelis upscale --instrumented
printf "Testing bin/fidelis upscale --instrumented...\n"
cli_out="$out_dir/cli_upscaled.png"
cli_manifest="$out_dir/cli_manifest.json"
"$repo_root/bin/fidelis" upscale \
  "$repo_root/tests/fixtures/product_hard_edges.png" \
  "$cli_out" \
  --model RealeSR-general-v3 \
  --instrumented \
  --json-manifest "$cli_manifest"

[[ -s "$cli_out" ]] || { printf "CLI output missing!\n" >&2; exit 1; }
[[ -s "$cli_manifest" ]] || { printf "CLI manifest missing!\n" >&2; exit 1; }

# Verify golden dataset
printf "Testing Fidelis Golden Dataset in v2/evals/fidelis/golden_cases.jsonl...\n"
golden_path="$repo_root/v2/evals/fidelis/golden_cases.jsonl"
[[ -s "$golden_path" ]] || { printf "Golden cases file missing!\n" >&2; exit 1; }

"$python_bin" -c '
import json, sys
cases = []
with open(sys.argv[1]) as f:
    for line in f:
        if line.strip():
            cases.append(json.loads(line))
assert len(cases) >= 20, f"Expected >= 20 golden cases, found {len(cases)}"
content_types = {c["content_type"] for c in cases}
for req in ["portrait", "anime", "text_document", "low_light", "macro_texture"]:
    assert req in content_types, f"Missing domain: {req}"
print(f"Golden dataset verified: {len(cases)} cases across 5 domains.")
' "$golden_path"

printf "All Fidelis pipeline instrumentation tests passed successfully!\n"
