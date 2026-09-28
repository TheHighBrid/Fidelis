#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
catalog="${FIDELIS_CANDIDATE_CATALOG:-$repo_root/config/photo-candidates.tsv}"
source_root="${FIDELIS_CANDIDATE_SOURCE_ROOT:-https://huggingface.co/tumuyan2/realsr-models/resolve}"
# Unlike :-, the single-hyphen form preserves an explicitly empty suffix. That
# is useful for local file:// fixtures while retaining ?download=true normally.
url_suffix="${FIDELIS_CANDIDATE_URL_SUFFIX-?download=true}"
cli="${FIDELIS_CLI:-fidelis}"

usage() {
  cat <<'EOF'
Usage:
  scripts/install-photo-candidate.sh list
  scripts/install-photo-candidate.sh MODEL [--replace]

Downloads a pinned Fidelis photo-model candidate, verifies both NCNN files by
SHA-256, then installs it through `fidelis model-add`.
EOF
}

[[ -s "$catalog" ]] || { printf 'Candidate catalog not found: %s\n' "$catalog" >&2; exit 1; }

list_candidates() {
  awk -F '\t' '
    $0 !~ /^#/ && NF >= 7 {
      printf "%-22s  %-17s  %s\n", $1, $2, $7
    }
  ' "$catalog"
}

load_candidate() {
  local wanted="$1"
  local row
  row="$(awk -F '\t' -v wanted="$wanted" '$0 !~ /^#/ && $1 == wanted {print; exit}' "$catalog")"
  [[ -n "$row" ]] || {
    printf 'Unknown photo candidate: %s\nAvailable candidates:\n' "$wanted" >&2
    list_candidates >&2
    return 1
  }
  IFS=$'\t' read -r name role revision folder param_sha bin_sha license_note <<<"$row"
}

command="${1:-}"
case "$command" in
  list)
    [[ $# -eq 1 ]] || { usage >&2; exit 2; }
    list_candidates
    exit 0
    ;;
  ''|-h|--help|help)
    usage
    exit 0
    ;;
esac

[[ $# -eq 1 || $# -eq 2 ]] || { usage >&2; exit 2; }
replace="${2:-}"
[[ -z "$replace" || "$replace" == "--replace" ]] || { usage >&2; exit 2; }

for dependency in curl sha256sum jq; do
  command -v "$dependency" >/dev/null 2>&1 || {
    printf 'Required command is missing: %s\n' "$dependency" >&2
    exit 1
  }
done

load_candidate "$command"

tmp="$(mktemp -d "${TMPDIR:-/tmp}/fidelis-photo-candidate.XXXXXX")"
metadata_tmp=""
trap 'rm -rf "$tmp"; [[ -n "$metadata_tmp" ]] && rm -f "$metadata_tmp"' EXIT

param_url="$source_root/$revision/$folder/x4.param$url_suffix"
bin_url="$source_root/$revision/$folder/x4.bin$url_suffix"
param_file="$tmp/x4.param"
bin_file="$tmp/x4.bin"

printf 'Downloading %s (%s)...\n' "$name" "$role"
curl -fsSL --retry 3 --retry-delay 2 "$param_url" -o "$param_file"
curl -fsSL --retry 3 --retry-delay 2 "$bin_url" -o "$bin_file"

[[ -s "$param_file" && -s "$bin_file" ]] || {
  printf 'Candidate download was empty or incomplete: %s\n' "$name" >&2
  exit 1
}

actual_param_sha="$(sha256sum "$param_file" | awk '{print $1}')"
actual_bin_sha="$(sha256sum "$bin_file" | awk '{print $1}')"

if [[ "$actual_param_sha" != "$param_sha" || "$actual_bin_sha" != "$bin_sha" ]]; then
  printf 'Candidate checksum mismatch: %s\n' "$name" >&2
  printf '  param expected %s\n  param actual   %s\n' "$param_sha" "$actual_param_sha" >&2
  printf '  bin   expected %s\n  bin   actual   %s\n' "$bin_sha" "$actual_bin_sha" >&2
  exit 1
fi

args=(model-add "$name" "$param_file" "$bin_file")
[[ "$replace" == "--replace" ]] && args+=(--replace)
"$cli" "${args[@]}"

app_home="${FIDELIS_HOME:-$HOME/.local/share/fidelis}"
metadata="$app_home/runtime/models-$name/fidelis-model.json"
[[ -s "$metadata" ]] || {
  printf 'Installed model metadata is missing: %s\n' "$metadata" >&2
  exit 1
}

metadata_tmp="$metadata.new.$$"
jq \
  --arg role "$role" \
  --arg repository "tumuyan2/realsr-models" \
  --arg revision "$revision" \
  --arg folder "$folder" \
  --arg license_note "$license_note" \
  '.source = {type:"pinned-remote",repository:$repository,revision:$revision,folder:$folder}
   | .candidate = {role:$role,license_note:$license_note}' \
  "$metadata" > "$metadata_tmp"
mv "$metadata_tmp" "$metadata"
metadata_tmp=""

# Re-read through the public command so the final state is validated by the
# same integrity path used during future auditions.
"$cli" model-info "$name" >/dev/null

printf 'Candidate ready: %s\n' "$name"
printf 'Role: %s\n' "$role"
printf 'License note: %s\n' "$license_note"
