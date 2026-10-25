#!/usr/bin/env bash
set -Eeuo pipefail

readonly APP_HOME="${FIDELIS_HOME:-$HOME/.local/share/fidelis}"
readonly RUNTIME="$APP_HOME/runtime"
readonly BIN_HOME="${FIDELIS_BIN_DIR:-$HOME/.local/bin}"
readonly RELEASE_URL_REALSR="https://github.com/nihui/realsr-ncnn-vulkan/releases/download/20220728/realsr-ncnn-vulkan-20220728-macos.zip"
readonly RELEASE_URL_REALESRGAN="https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesrgan-ncnn-vulkan-20220424-macos.zip"

die() {
  printf 'Fidelis macOS install error: %s\n' "$*" >&2
  exit 1
}

[[ "$(uname -s)" == "Darwin" ]] || die "This installer is for macOS (Darwin)."

for dep in curl unzip jq; do
  command -v "$dep" >/dev/null 2>&1 || die "Missing required dependency: $dep"
done

if ! command -v sha256sum >/dev/null 2>&1 && command -v shasum >/dev/null 2>&1; then
  sha256sum() {
    shasum -a 256 "$@"
  }
fi

tmp_dir="$(mktemp -d "${TMPDIR:-/tmp}/fidelis-macos.XXXXXX")"
trap 'rm -rf "$tmp_dir"' EXIT

printf 'Downloading native macOS RealSR NCNN runtime...\n'
curl -fsSL --retry 3 --retry-delay 2 "$RELEASE_URL_REALSR" -o "$tmp_dir/realsr.zip"
unzip -q "$tmp_dir/realsr.zip" -d "$tmp_dir/realsr_staged"

printf 'Downloading native macOS Real-ESRGAN NCNN runtime...\n'
curl -fsSL --retry 3 --retry-delay 2 "$RELEASE_URL_REALESRGAN" -o "$tmp_dir/realesrgan.zip"
unzip -q "$tmp_dir/realesrgan.zip" -d "$tmp_dir/realesrgan_staged"

rm -f "$RUNTIME/realsr-ncnn" "$RUNTIME/realsr-ncnn-vulkan" "$RUNTIME/realsr-binary" "$RUNTIME/realesrgan-binary"
cp -f "$tmp_dir/realsr_staged/realsr-ncnn-vulkan-20220728-macos/realsr-ncnn-vulkan" "$RUNTIME/realsr-binary"
cp -f "$tmp_dir/realesrgan_staged/realesrgan-ncnn-vulkan" "$RUNTIME/realesrgan-binary"
chmod +x "$RUNTIME/realsr-binary" "$RUNTIME/realesrgan-binary"

# Install bundled DF2K model
if [[ -d "$tmp_dir/realsr_staged/realsr-ncnn-vulkan-20220728-macos/models-DF2K" ]]; then
  cp -a "$tmp_dir/realsr_staged/realsr-ncnn-vulkan-20220728-macos/models-DF2K" "$RUNTIME/"
  df2k_dir="$RUNTIME/models-DF2K"
  df2k_param_sha="$(sha256sum "$df2k_dir/x4.param" | awk '{print $1}')"
  df2k_bin_sha="$(sha256sum "$df2k_dir/x4.bin" | awk '{print $1}')"
  installed_at="$(date -u +'%Y-%m-%dT%H:%M:%SZ')"
  jq -n \
    --arg name "DF2K" \
    --arg engine "realsr-ncnn" \
    --arg format "ncnn" \
    --argjson scale 4 \
    --arg installed_at "$installed_at" \
    --arg source_type "bundled-macos-upstream" \
    --arg upstream_repo "nihui/realsr-ncnn-vulkan" \
    --arg param_sha256 "$df2k_param_sha" \
    --arg bin_sha256 "$df2k_bin_sha" \
    '{schema_version:1,name:$name,engine:$engine,format:$format,scale:$scale,installed_at:$installed_at,source:{type:$source_type,repository:$upstream_repo},sha256:{param:$param_sha256,bin:$bin_sha256}}' \
    > "$df2k_dir/fidelis-model.json"
  printf 'Installed and registered baseline model: DF2K\n'
fi

# Create unified wrapper executable at $RUNTIME/realsr-ncnn
cat > "$RUNTIME/realsr-ncnn" <<'WRAPPER'
#!/usr/bin/env bash
set -Eeuo pipefail

runtime_dir="$(cd "$(dirname "$0")" && pwd)"
input="" output="" model="" scale=4 tile=0 extra=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    -i) input="$2"; shift 2 ;;
    -o) output="$2"; shift 2 ;;
    -m) model="$2"; shift 2 ;;
    -s) scale="$2"; shift 2 ;;
    -t) tile="$2"; shift 2 ;;
    -h|--help)
      printf 'Fidelis macOS NCNN Unified Runtime\n'
      "$runtime_dir/realesrgan-binary" -h 2>&1 || true
      exit 0
      ;;
    *) extra+=("$1"); shift ;;
  esac
done

[[ -n "$input" && -n "$output" && -n "$model" ]] || {
  printf 'Usage: realsr-ncnn -i input -o output -m model_path\n' >&2
  exit 2
}

model_name="$(basename "$model")"
model_name="${model_name#models-}"

# If DF2K with realsr-binary
if [[ "$model_name" =~ ^(DF2K|DF2K_JPEG)$ && -x "$runtime_dir/realsr-binary" ]]; then
  exec "$runtime_dir/realsr-binary" -i "$input" -o "$output" -m "$model" -s "$scale" -t "$tile" ${extra[@]+"${extra[@]}"}
fi

# Dispatch via realesrgan-binary
stage_root="$(mktemp -d "${TMPDIR:-/tmp}/fidelis-models.XXXXXX")"
staging="$stage_root/models"
mkdir -p "$staging"
trap 'rm -rf "$stage_root"' EXIT

layer_count="$(awk 'NR==2 {print $1}' "$model/x4.param" 2>/dev/null || echo 0)"

if [[ "$model_name" =~ (general|v3|compact|anime) ]] || (( layer_count < 200 )); then
  # Compact SRVGGNet model
  ln -sf "$model/x4.param" "$staging/realesr-animevideov3-x4.param"
  ln -sf "$model/x4.bin" "$staging/realesr-animevideov3-x4.bin"
  exec "$runtime_dir/realesrgan-binary" -i "$input" -o "$output" -m "$staging" -n realesr-animevideov3 -s "$scale" -t "$tile" ${extra[@]+"${extra[@]}"}
else
  # RRDBNet model (Nomos, Remacri, etc.)
  ln -sf "$model/x4.param" "$staging/realesrgan-x4plus.param"
  ln -sf "$model/x4.bin" "$staging/realesrgan-x4plus.bin"
  exec "$runtime_dir/realesrgan-binary" -i "$input" -o "$output" -m "$staging" -n realesrgan-x4plus -s "$scale" -t "$tile" ${extra[@]+"${extra[@]}"}
fi
WRAPPER
chmod +x "$RUNTIME/realsr-ncnn"
ln -sf "$RUNTIME/realsr-ncnn" "$RUNTIME/realsr-ncnn-vulkan"

# Install CLI binary
mkdir -p "$BIN_HOME"
repo_root="$(cd "$(dirname "$0")/.." && pwd)"
cp -f "$repo_root/bin/fidelis" "$BIN_HOME/fidelis"
chmod +x "$BIN_HOME/fidelis"

mkdir -p "$APP_HOME"
jq -n --arg os "Darwin" --arg arch "$(uname -m)" --arg runtime "realsr-ncnn-vulkan-20220728" \
  '{os:$os, architecture:$arch, engine:$runtime}' > "$APP_HOME/install.json"

printf '\nNative macOS NCNN runtime installed successfully.\n'
printf 'Runtime binary: %s\n' "$RUNTIME/realsr-ncnn"
printf 'CLI installed to: %s/fidelis\n' "$BIN_HOME"
printf 'Make sure %s is in your PATH (e.g. export PATH="%s:$PATH").\n' "$BIN_HOME" "$BIN_HOME"
printf '\nNext steps:\n'
printf '  1. Run: %s/fidelis doctor\n' "$BIN_HOME"
printf '  2. Install curated photo candidates: bash scripts/install-photo-candidate.sh RealeSR-general-v3\n'
printf '  3. Audition models: %s/fidelis audition input.png ./audition\n' "$BIN_HOME"
