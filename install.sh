#!/data/data/com.termux/files/usr/bin/bash
set -Eeuo pipefail

readonly APP_HOME="${FIDELIS_HOME:-$HOME/.local/share/fidelis}"
readonly BIN_HOME="${PREFIX:-/data/data/com.termux/files/usr}/bin"
readonly API_URL="https://api.github.com/repos/tumuyan/RealSR-NCNN-Android/releases/latest"

die() {
  printf 'Fidelis install error: %s\n' "$*" >&2
  exit 1
}

[[ "$(uname -m)" == "aarch64" ]] || die "ARM64/aarch64 is required."
[[ -n "${PREFIX:-}" && "$PREFIX" == /data/data/com.termux/files/usr ]] || die "Run this in native Termux, not proot."

available_kb="$(df -Pk "$HOME" | awk 'NR == 2 {print $4}')"
[[ "$available_kb" =~ ^[0-9]+$ ]] || die "Could not determine free storage."
(( available_kb >= 700000 )) || die "At least 700 MB of free Termux storage is required."

pkg install -y curl jq unzip file

tmp_dir="$(mktemp -d "${TMPDIR:-$PREFIX/tmp}/fidelis.XXXXXX")"
trap 'rm -rf "$tmp_dir"' EXIT

release_json="$tmp_dir/release.json"
curl -fsSL --retry 3 --retry-delay 2 "$API_URL" -o "$release_json"

asset_json="$(jq -c '[.assets[] | select(.name | test("GUI-armv8a.*\\.apk$"))][0]' "$release_json")"
[[ "$asset_json" != "null" ]] || die "The latest release has no ARM64 APK asset."

version="$(jq -r '.tag_name' "$release_json")"
asset_name="$(jq -r '.name' <<<"$asset_json")"
asset_url="$(jq -r '.browser_download_url' <<<"$asset_json")"
expected_digest="$(jq -r '.digest // empty' <<<"$asset_json")"
apk="$tmp_dir/$asset_name"

printf 'Downloading upstream %s (%s)...\n' "$version" "$asset_name"
curl -fL --retry 3 --retry-delay 2 "$asset_url" -o "$apk"

if [[ "$expected_digest" == sha256:* ]]; then
  expected_sha="${expected_digest#sha256:}"
  actual_sha="$(sha256sum "$apk" | awk '{print $1}')"
  [[ "$actual_sha" == "$expected_sha" ]] || die "APK checksum mismatch."
else
  die "Upstream release does not provide a SHA-256 digest."
fi

staging="$tmp_dir/staging"
mkdir -p "$staging"
unzip -q "$apk" 'assets/realsr/*' -d "$staging" || die "Expected runtime is absent from the APK."

runtime_source="$staging/assets/realsr"
[[ -f "$runtime_source/realsr-ncnn" ]] || die "realsr-ncnn was not found in the APK."
[[ -d "$runtime_source/models-ESRGAN-Nomos8kSC" ]] || die "Nomos8kSC was not found in the APK."

rm -rf "$APP_HOME/runtime.new"
mkdir -p "$APP_HOME/runtime.new"
cp -a "$runtime_source/." "$APP_HOME/runtime.new/"
chmod +x "$APP_HOME/runtime.new/realsr-ncnn" "$APP_HOME/runtime.new/resize-ncnn" 2>/dev/null || true

# Register the bundled baseline model with the same provenance format used by
# `fidelis model-add`. This does not claim that Nomos is the accepted quality
# target; it only makes the baseline reproducible and auditable.
bundled_model="$APP_HOME/runtime.new/models-ESRGAN-Nomos8kSC"
[[ -s "$bundled_model/x4.param" && -s "$bundled_model/x4.bin" ]] || die "Bundled Nomos8kSC model files are incomplete."
bundled_param_sha="$(sha256sum "$bundled_model/x4.param" | awk '{print $1}')"
bundled_bin_sha="$(sha256sum "$bundled_model/x4.bin" | awk '{print $1}')"
installed_at="$(date -u +'%Y-%m-%dT%H:%M:%SZ')"
jq -n \
  --arg name "ESRGAN-Nomos8kSC" \
  --arg engine "realsr-ncnn" \
  --arg format "ncnn" \
  --argjson scale 4 \
  --arg installed_at "$installed_at" \
  --arg source_type "bundled-upstream" \
  --arg upstream_repo "tumuyan/RealSR-NCNN-Android" \
  --arg upstream_version "$version" \
  --arg upstream_asset "$asset_name" \
  --arg param_sha256 "$bundled_param_sha" \
  --arg bin_sha256 "$bundled_bin_sha" \
  '{schema_version:1,name:$name,engine:$engine,format:$format,scale:$scale,installed_at:$installed_at,source:{type:$source_type,repository:$upstream_repo,version:$upstream_version,asset:$upstream_asset},sha256:{param:$param_sha256,bin:$bin_sha256}}' \
  > "$bundled_model/fidelis-model.json"

rm -rf "$APP_HOME/runtime"
mv "$APP_HOME/runtime.new" "$APP_HOME/runtime"

mkdir -p "$APP_HOME"
jq -n --arg version "$version" --arg asset "$asset_name" --arg sha256 "$actual_sha" \
  '{upstream_version:$version, asset:$asset, sha256:$sha256}' > "$APP_HOME/install.json"

install -m 0755 "$(cd "$(dirname "$0")" && pwd)/bin/fidelis" "$BIN_HOME/fidelis"

printf '\nFidelis %s installed.\nRun: fidelis doctor\n' "$version"
