#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
export COPYFILE_DISABLE=1
python_bin="$repo_root/.venv/bin/python"
if [[ ! -x "$python_bin" ]]; then
  python_bin="$(command -v python3)"
fi
version="${1:-${VERSION:-3.0.0}}"
version="${version#v}" # Strip leading v if present
dist_dir="$repo_root/dist"
mkdir -p "$dist_dir"

if ! command -v sha256sum >/dev/null 2>&1 && command -v shasum >/dev/null 2>&1; then
  sha256sum() { shasum -a 256 "$@"; }
fi

printf 'Packaging Fidelis v%s release...\n' "$version"

archive_base="fidelis-v${version}"
tar_gz="$dist_dir/${archive_base}.tar.gz"
zip_out="$dist_dir/${archive_base}.zip"

rm -f "$tar_gz" "$zip_out" "$tar_gz.sha256" "$zip_out.sha256"
"$python_bin" - "$repo_root" "$tar_gz" "$zip_out" <<'PY'
import sys
from pathlib import Path

repo_root = Path(sys.argv[1]).resolve()
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from fidelis.studio.packaging import (
    create_deterministic_tar_gz,
    create_deterministic_zip,
)

create_deterministic_tar_gz(repo_root, sys.argv[2])
create_deterministic_zip(repo_root, sys.argv[3])
PY

printf 'Created tarball: %s (%s)\n' "$tar_gz" "$(du -h "$tar_gz" | awk '{print $1}')"
printf 'Created zip:     %s (%s)\n' "$zip_out" "$(du -h "$zip_out" | awk '{print $1}')"

sha256sum "$tar_gz" > "$tar_gz.sha256"
[[ -f "$zip_out" ]] && sha256sum "$zip_out" > "$zip_out.sha256"

printf '\nRelease packaging complete. Hashes:\n'
cat "$dist_dir"/*.sha256
