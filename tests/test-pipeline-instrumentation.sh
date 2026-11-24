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
receiver_pid=""
cleanup() {
  if [[ -n "$receiver_pid" ]] && kill -0 "$receiver_pid" 2>/dev/null; then
    kill "$receiver_pid" 2>/dev/null || true
    wait "$receiver_pid" 2>/dev/null || true
  fi
  rm -rf "$out_dir"
}
trap cleanup EXIT

export PATH="$(dirname "$python_bin"):$PATH"

# Start an ephemeral local 127.0.0.1 telemetry receiver to test live span ingestion
receiver_port_file="$out_dir/receiver_port.txt"
received_payload="$out_dir/received_telemetry.json"
"$python_bin" -c '
import http.server, json, sys
from pathlib import Path

port_file = Path(sys.argv[1])
payload_file = Path(sys.argv[2])

class Handler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        payload_file.write_bytes(body)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        resp = json.dumps({"status": "ok"}).encode("utf-8")
        self.send_header("Content-Length", str(len(resp)))
        self.end_headers()
        self.wfile.write(resp)
    def log_message(self, format, *args):
        return

srv = http.server.HTTPServer(("127.0.0.1", 0), Handler)
port_file.write_text(str(srv.server_address[1]), encoding="utf-8")
srv.handle_request()
srv.server_close()
' "$receiver_port_file" "$received_payload" &
receiver_pid=$!

for _ in $(seq 1 50); do
  if [[ -s "$receiver_port_file" ]]; then
    break
  fi
  sleep 0.1
done
[[ -s "$receiver_port_file" ]] || { printf "Telemetry receiver failed to start!\n" >&2; exit 1; }
receiver_port="$(cat "$receiver_port_file")"

manifest_out="$out_dir/manifest.json"
img_out="$out_dir/upscaled.png"

# Run instrumented upscaling via CLI against local 127.0.0.1 receiver
"$python_bin" "$repo_root/scripts/upscale.py" \
  "$repo_root/tests/fixtures/portrait_skin.png" \
  "$img_out" \
  --model realesrgan-x4plus \
  --tile-size 256 \
  --telemetry-url "http://127.0.0.1:${receiver_port}/api/telemetry/trace?project=fidelis" \
  --json-manifest "$manifest_out"

[[ -s "$img_out" ]] || { printf "Output image missing!\n" >&2; exit 1; }
[[ -s "$manifest_out" ]] || { printf "Manifest missing!\n" >&2; exit 1; }
[[ -s "$out_dir/upscaled.png.c2pa.json" ]] || { printf "C2PA sidecar manifest missing!\n" >&2; exit 1; }
[[ -s "$received_payload" ]] || { printf "Mock telemetry receiver did not receive payload!\n" >&2; exit 1; }

# Verify JSON manifest fields and received companion telemetry payload
"$python_bin" -c '
import json, sys
with open(sys.argv[1]) as f:
    m = json.load(f)
with open(sys.argv[2]) as f:
    rx = json.load(f)

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
assert c2pa == "unsigned", f"Bad C2PA status: {c2pa}"
assert m["exif_preserved"] is True, "EXIF preservation should be true"
assert m["zero_black_tiles"] is True, "Zero black tiles should be true"
assert "metrics" in m, "Manifest must contain metrics"
assert m["metrics"]["psnr"] > 0, "PSNR must be positive"
assert m["metrics"]["ssim"] > 0, "SSIM must be positive"
assert m["metrics"]["lpips"] is None, "LPIPS must remain null when unavailable"
assert m["metrics"]["gradient_distance_proxy"] is not None, "Gradient proxy must be recorded"
assert "tile_execution" in m, "Manifest must contain tile_execution"
assert m["tile_execution"]["tile_size"] == 256, "Tile execution must record tile_size"
assert m["telemetry_posted"] is True, "Telemetry must be successfully posted to receiver"
assert m["telemetry_response"].get("status") == "ok", "Telemetry response status must be ok"
span_count = len(m["spans"])
assert span_count >= 3, f"Expected at least 3 spans, got {span_count}"

# Verify companion-telemetry-contracts.md payload attributes received by server
for key in (
    "input_dimensions",
    "noise_level",
    "model_profile",
    "tile_size",
    "vram_peak_mb",
    "processing_time_per_megapixel",
    "c2pa_status",
    "metrics",
    "metric_context",
    "spans",
):
    assert key in rx, f"Missing companion telemetry attribute: {key}"
assert rx["metrics"]["lpips"] is None, "Received telemetry LPIPS must be null"
print("Manifest and live local telemetry verification passed successfully.")
' "$manifest_out" "$received_payload"

# Test CLI integration: bin/fidelis upscale --instrumented with offline telemetry receiver
# Must succeed non-blockingly and record telemetry_posted=False, status=unreachable
printf "Testing bin/fidelis upscale --instrumented (non-blocking offline telemetry)...\n"
closed_port="$("$python_bin" -c '
import socket
s = socket.socket()
s.bind(("127.0.0.1", 0))
port = s.getsockname()[1]
s.close()
print(port)
')"
cli_out="$out_dir/cli_upscaled.png"
cli_manifest="$out_dir/cli_manifest.json"
FIDELIS_TELEMETRY_URL="http://127.0.0.1:${closed_port}/api/telemetry/trace?project=fidelis" \
"$repo_root/bin/fidelis" upscale \
  "$repo_root/tests/fixtures/product_hard_edges.png" \
  "$cli_out" \
  --model RealeSR-general-v3 \
  --instrumented \
  --json-manifest "$cli_manifest"

[[ -s "$cli_out" ]] || { printf "CLI output missing!\n" >&2; exit 1; }
[[ -s "$cli_manifest" ]] || { printf "CLI manifest missing!\n" >&2; exit 1; }
"$python_bin" -c '
import json, sys
with open(sys.argv[1]) as f:
    m = json.load(f)
assert m["telemetry_posted"] is False, "Offline receiver must record telemetry_posted=False"
resp = m.get("telemetry_response") or {}
assert resp.get("status") == "unreachable", f"Unexpected offline telemetry status: {resp}"
c2pa = m["c2pa_status"]
assert c2pa == "unsigned", f"Bad C2PA status: {c2pa}"
print("Offline non-blocking telemetry fallback verified.")
' "$cli_manifest"

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
