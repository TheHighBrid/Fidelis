#!/data/data/com.termux/files/usr/bin/bash
set -Eeuo pipefail

readonly APP_HOME="${FIDELIS_HOME:-$HOME/.local/share/fidelis}"
readonly BIN_HOME="${PREFIX:-/data/data/com.termux/files/usr}/bin"

die() {
  printf 'Fidelis install error: %s\n' "$*" >&2
  exit 1
}

[[ "$(uname -m)" == "aarch64" ]] || die "ARM64/aarch64 is required."
[[ -n "${PREFIX:-}" && "$PREFIX" == /data/data/com.termux/files/usr ]] || die "Run this in native Termux, not proot."

pkg install -y termux-tools
mkdir -p "$APP_HOME"

# The retired NCNN runtime is app-owned and produced visibly corrupted output.
# Remove it during the v2 upgrade so it cannot be selected accidentally.
if [[ -d "$APP_HOME/runtime" ]]; then
  printf 'Removing retired NCNN runtime...\n'
  rm -rf "$APP_HOME/runtime"
fi

cat > "$APP_HOME/install.json" <<'JSON'
{
  "version": "2.0.0",
  "backend": "VOSR 2.0 on interactive Google Colab",
  "legacy_ncnn": "retired"
}
JSON

install -m 0755 "$(cd "$(dirname "$0")" && pwd)/bin/fidelis" "$BIN_HOME/fidelis"

printf '\nFidelis 2.0 installed.\nRun: fidelis open\n'

