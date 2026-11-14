#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
export COPYFILE_DISABLE=1
version="${1:-${VERSION:-3.0.0}}"
version="${version#v}"

dist_dir="$repo_root/dist"
mkdir -p "$dist_dir"

bundle_name="fidelis-offline-bundle-v${version}"
bundle_dir="$dist_dir/$bundle_name"
rm -rf "$bundle_dir"
mkdir -p "$bundle_dir"

printf 'Building Fidelis air-gapped offline bundle (v%s)...\n' "$version"

# 1. Copy core repository files
exclude_patterns=(
  --exclude='.git'
  --exclude='.venv'
  --exclude='__pycache__'
  --exclude='*.pyc'
  --exclude='*.pyo'
  --exclude='*.pyd'
  --exclude='*.old.*'
  --exclude='.cache'
  --exclude='.fidelis'
  --exclude='dist'
  --exclude='runtime'
  --exclude='models'
  --exclude='experiments/eval_crops/audition_*'
  --exclude='experiments/eval_crops/web_audition'
  --exclude='experiments/self_improvement/outputs'
  --exclude='experiments/eval_corpus'
  --exclude='fidelis-tile_*'
  --exclude='*.apk'
  --exclude='.env'
  --exclude='.env.*'
  --exclude='.DS_Store'
  --exclude='config/release-candidate-v1.json'
)

tmp_core_tar="$(mktemp "${TMPDIR:-/tmp}/fidelis-core-tar.XXXXXX")"
tar -czf "$tmp_core_tar" -C "$repo_root" "${exclude_patterns[@]}" .
tar -xzf "$tmp_core_tar" -C "$bundle_dir"
rm -f "$tmp_core_tar"

# 2. Package model weights
models_staging="$bundle_dir/offline_models"
mkdir -p "$models_staging"

fidelis_runtime="${FIDELIS_HOME:-$HOME/.local/share/fidelis}/runtime"
models_found=0

if [[ -d "$fidelis_runtime" ]]; then
  for mdir in "$fidelis_runtime"/models-*; do
    if [[ -d "$mdir" ]]; then
      mname="$(basename "$mdir")"
      printf '  Packaging model: %s\n' "$mname"
      cp -R "$mdir" "$models_staging/$mname"
      models_found=$((models_found + 1))
    fi
  done
fi

if [[ $models_found -eq 0 ]]; then
  printf 'Warning: No installed models found in %s\n' "$fidelis_runtime" >&2
  printf 'Run: bash scripts/install-photo-candidate.sh RealeSR-general-v3 first to bundle weights.\n' >&2
fi

# 3. Create self-contained install-offline.sh inside bundle
cat > "$bundle_dir/install-offline.sh" <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail

bundle_root="$(cd "$(dirname "$0")" && pwd)"
app_home="${FIDELIS_HOME:-$HOME/.local/share/fidelis}"
runtime_dir="$app_home/runtime"
mkdir -p "$runtime_dir" "$app_home/bin"

printf 'Installing Fidelis from offline bundle...\n'

# 1. Install CLI
cp "$bundle_root/bin/fidelis" "$app_home/bin/fidelis"
chmod +x "$app_home/bin/fidelis"

# 2. Install bundled models
if [[ -d "$bundle_root/offline_models" ]]; then
  for mdir in "$bundle_root/offline_models"/models-*; do
    if [[ -d "$mdir" ]]; then
      mname="$(basename "$mdir")"
      target="$runtime_dir/$mname"
      printf '  Deploying %s -> %s\n' "$mname" "$target"
      rm -rf "$target"
      cp -R "$mdir" "$target"
    fi
  done
fi

printf '\nOffline installation complete.\n'
printf 'Add to your PATH:\n'
printf '  export PATH="%s/bin:$PATH"\n' "$app_home"
printf 'Verify with:\n'
printf '  fidelis models\n'
EOF

chmod +x "$bundle_dir/install-offline.sh"

# 4. Create archive
archive_tar="$dist_dir/${bundle_name}.tar.gz"
tar -czf "$archive_tar" -C "$dist_dir" "$bundle_name"
rm -rf "$bundle_dir"

if ! command -v sha256sum >/dev/null 2>&1 && command -v shasum >/dev/null 2>&1; then
  sha256sum() { shasum -a 256 "$@"; }
fi

sha256sum "$archive_tar" > "$archive_tar.sha256"

printf '\nAir-gapped offline bundle created successfully:\n'
printf '  Archive: %s (%s)\n' "$archive_tar" "$(du -h "$archive_tar" | awk '{print $1}')"
printf '  SHA-256: '
cat "$archive_tar.sha256"
