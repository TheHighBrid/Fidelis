#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
version="3.0.0"
dist_dir="$repo_root/dist"
mkdir -p "$dist_dir"

printf 'Packaging Fidelis v%s release...\n' "$version"

archive_base="fidelis-v${version}"
tar_gz="$dist_dir/${archive_base}.tar.gz"
zip_out="$dist_dir/${archive_base}.zip"

# Exclude temporary and local development artifacts
exclude_patterns=(
  --exclude='.git'
  --exclude='.venv'
  --exclude='__pycache__'
  --exclude='*.pyc'
  --exclude='*.old.*'
  --exclude='dist'
  --exclude='fidelis-tile_*'
  --exclude='.DS_Store'
)

tar -czf "$tar_gz" -C "$repo_root" "${exclude_patterns[@]}" .
printf 'Created tarball: %s (%s)\n' "$tar_gz" "$(du -h "$tar_gz" | awk '{print $1}')"

if command -v zip >/dev/null 2>&1; then
  tmp_zip_dir="$(mktemp -d "${TMPDIR:-/tmp}/fidelis-zip.XXXXXX")"
  tar -xzf "$tar_gz" -C "$tmp_zip_dir"
  (cd "$tmp_zip_dir" && zip -rq "$zip_out" .)
  rm -rf "$tmp_zip_dir"
  printf 'Created zip:     %s (%s)\n' "$zip_out" "$(du -h "$zip_out" | awk '{print $1}')"
fi

sha256sum "$tar_gz" > "$tar_gz.sha256"
[[ -f "$zip_out" ]] && sha256sum "$zip_out" > "$zip_out.sha256"

printf '\nRelease packaging complete. Hashes:\n'
cat "$dist_dir"/*.sha256
