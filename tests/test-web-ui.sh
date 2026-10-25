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

port=18942
"$python_bin" "$repo_root/scripts/web-ui.py" -p "$port" &
server_pid=$!
trap 'kill "$server_pid" 2>/dev/null || true' EXIT

# Wait for server to start
for _ in {1..20}; do
  if curl -s "http://127.0.0.1:$port/" >/dev/null 2>&1; then
    break
  fi
  sleep 0.2
done

# Test HTML root
html_out="$(curl -s "http://127.0.0.1:$port/")"
echo "$html_out" | grep -Fq "Fidelis Photographic Restoration Studio"

# Test models API
models_json="$(curl -s "http://127.0.0.1:$port/api/models")"
echo "$models_json" | grep -Fq "RealeSR-general-v3"

kill "$server_pid" 2>/dev/null || true
trap - EXIT

printf 'Web UI server tests passed.\n'
