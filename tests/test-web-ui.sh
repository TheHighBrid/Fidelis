#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"

python_bin="${PYTHON_BIN:-}"
if [[ -z "$python_bin" ]]; then
  if [[ -x "$repo_root/.venv/bin/python" ]]; then
    python_bin="$repo_root/.venv/bin/python"
  elif python3 -c "import PIL" >/dev/null 2>&1; then
    python_bin="python3"
  else
    python_bin="python3"
  fi
fi

# A deterministic 4x fake NCNN engine tests the real HTTP pipeline without
# downloading model weights or requiring a GPU. The output must still satisfy
# the CLI's size and model registry contract.
test_home="$(mktemp -d "${TMPDIR:-/tmp}/fidelis-webui-home.XXXXXX")"
export FIDELIS_HOME="$test_home"
runtime="$FIDELIS_HOME/runtime"
mkdir -p "$runtime/models-RealeSR-general-v3"
printf 'test-model-param\n' > "$runtime/models-RealeSR-general-v3/x4.param"
printf 'test-model-bin\n' > "$runtime/models-RealeSR-general-v3/x4.bin"
cat > "$runtime/realsr-ncnn" <<'PY'
#!/usr/bin/env python3
import sys
from PIL import Image

args = sys.argv[1:]
source = args[args.index("-i") + 1]
target = args[args.index("-o") + 1]
with Image.open(source) as im:
    im = im.convert("RGB")
    im.resize((im.width * 4, im.height * 4), Image.Resampling.NEAREST).save(target)
PY
chmod +x "$runtime/realsr-ncnn"

port=18942
"$python_bin" "$repo_root/scripts/web-ui.py" -p "$port" &
server_pid=$!
trap 'kill "$server_pid" 2>/dev/null || true; rm -rf "$test_home"' EXIT

# Wait for server to start
for _ in {1..20}; do
  if curl -s "http://127.0.0.1:$port/" >/dev/null 2>&1; then
    break
  fi
  sleep 0.2
done

# Test HTML root
html_out="$(curl -s "http://127.0.0.1:$port/")"
[[ "$html_out" == *"Fidelis Photographic Restoration Studio"* ]]
[[ "$html_out" == *"mode-single-btn"* ]]
[[ "$html_out" == *"mode-dual-btn"* ]]
[[ "$html_out" == *"preset-select"* ]]
[[ "$html_out" == *"creativity-slider"* ]]
[[ "$html_out" == *"resemblance-slider"* ]]
[[ "$html_out" == *"text-check"* ]]
[[ "$html_out" == *"color-fix-select"* ]]
[[ "$html_out" == *"profiler-panel"* ]]
[[ "$html_out" == *"portrait-check"* ]]
[[ "$html_out" == *"fidelity-slider"* ]]
[[ "$html_out" == *"user_test_blonde.png"* ]]

# Test models API
models_json="$(curl -s "http://127.0.0.1:$port/api/models")"
[[ "$models_json" == *"RealeSR-general-v3"* ]]

# Test Profiler API using temp json to avoid ARG_MAX limit
tmp_req="$(mktemp /tmp/fidelis_req_XXXXXX)"
"$python_bin" -c '
import base64, json, sys
with open(sys.argv[1], "rb") as f:
    b64 = base64.b64encode(f.read()).decode("ascii")
with open(sys.argv[2], "w") as out:
    json.dump({"image": f"data:image/png;base64,{b64}"}, out)
' "$repo_root/experiments/eval_crops/user_test_blonde.png" "$tmp_req"

prof_json="$(curl -s -X POST "http://127.0.0.1:$port/api/profile" \
  -H "Content-Type: application/json" \
  --data-binary @"$tmp_req")"
rm -f "$tmp_req"
[[ "$prof_json" == *"recommended_mode"* ]]
[[ "$prof_json" == *"blur_score"* ]]
[[ "$prof_json" == *"face_count"* ]]

# Test Upscale API
tmp_up="$(mktemp /tmp/fidelis_up_XXXXXX)"
"$python_bin" -c '
import base64, json, sys
with open(sys.argv[1], "rb") as f:
    b64 = base64.b64encode(f.read()).decode("ascii")
with open(sys.argv[2], "w") as out:
    json.dump({
        "image": f"data:image/png;base64,{b64}",
        "preset": "Fast_Fidelity",
        "model": "RealeSR-general-v3",
        "text_preserve": True,
        "color_fix": "wavelet"
    }, out)
' "$repo_root/tests/fixtures/portrait_skin.png" "$tmp_up"

up_json="$(curl -s -X POST "http://127.0.0.1:$port/api/upscale" \
  -H "Content-Type: application/json" \
  --data-binary @"$tmp_up")"
rm -f "$tmp_up"

[[ "$up_json" == *"download_url"* ]]
[[ "$up_json" == *"view_url"* ]]
[[ "$up_json" == *"metrics"* ]]
[[ "$up_json" == *"cielab_delta_e"* ]]

kill "$server_pid" 2>/dev/null || true
rm -rf "$test_home"
trap - EXIT

printf 'Web UI server tests passed.\n'
