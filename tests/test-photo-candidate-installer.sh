#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
installer="$repo_root/scripts/install-photo-candidate.sh"
work="$(mktemp -d "${TMPDIR:-/tmp}/fidelis-photo-installer-test.XXXXXX")"
trap 'rm -rf "$work"' EXIT

export FIDELIS_HOME="$work/home"
runtime="$FIDELIS_HOME/runtime"
mkdir -p "$runtime"

cat > "$runtime/realsr-ncnn" <<'SH'
#!/usr/bin/env bash
exit 0
SH
chmod +x "$runtime/realsr-ncnn"

cli_wrapper="$work/fidelis"
cat > "$cli_wrapper" <<SH
#!/usr/bin/env bash
exec bash "$repo_root/bin/fidelis" "\$@"
SH
chmod +x "$cli_wrapper"
export FIDELIS_CLI="$cli_wrapper"

revision="test-revision"
folder="models-TestPhoto"
source_dir="$work/source/$revision/$folder"
mkdir -p "$source_dir"
printf '7767517\n1 1\nInput data 0 1 data\n' > "$source_dir/x4.param"
printf 'test-model-weights\n' > "$source_dir/x4.bin"

param_sha="$(sha256sum "$source_dir/x4.param" | awk '{print $1}')"
bin_sha="$(sha256sum "$source_dir/x4.bin" | awk '{print $1}')"
catalog="$work/catalog.tsv"
printf '# name\trole\trevision\tfolder\tparam_sha256\tbin_sha256\tlicense_note\n' > "$catalog"
printf 'TestPhoto\tmobile-general\t%s\t%s\t%s\t%s\tTest-only license note\n' \
  "$revision" "$folder" "$param_sha" "$bin_sha" >> "$catalog"

export FIDELIS_CANDIDATE_CATALOG="$catalog"
export FIDELIS_CANDIDATE_SOURCE_ROOT="file://$work/source"
export FIDELIS_CANDIDATE_URL_SUFFIX=""

list_output="$(bash "$installer" list)"
printf '%s' "$list_output" | grep -Fq 'TestPhoto'
printf '%s' "$list_output" | grep -Fq 'mobile-general'

bash "$installer" TestPhoto
model_dir="$runtime/models-TestPhoto"
[[ -s "$model_dir/x4.param" && -s "$model_dir/x4.bin" ]]
[[ "$(sha256sum "$model_dir/x4.param" | awk '{print $1}')" == "$param_sha" ]]
[[ "$(sha256sum "$model_dir/x4.bin" | awk '{print $1}')" == "$bin_sha" ]]

jq -e \
  --arg revision "$revision" \
  --arg folder "$folder" \
  '.name == "TestPhoto"
   and .source.type == "pinned-remote"
   and .source.repository == "tumuyan2/realsr-models"
   and .source.revision == $revision
   and .source.folder == $folder
   and .candidate.role == "mobile-general"
   and .candidate.license_note == "Test-only license note"' \
  "$model_dir/fidelis-model.json" >/dev/null

# Corrupt the remote fixture. A replacement attempt must fail before touching
# the already installed model.
printf 'tampered-weights\n' > "$source_dir/x4.bin"
installed_sha_before="$(sha256sum "$model_dir/x4.bin" | awk '{print $1}')"
set +e
bash "$installer" TestPhoto --replace >"$work/tamper.out" 2>&1
rc=$?
set -e
[[ $rc -ne 0 ]]
grep -Fq 'Candidate checksum mismatch: TestPhoto' "$work/tamper.out"
[[ "$(sha256sum "$model_dir/x4.bin" | awk '{print $1}')" == "$installed_sha_before" ]]

set +e
bash "$installer" DoesNotExist >"$work/missing.out" 2>&1
rc=$?
set -e
[[ $rc -ne 0 ]]
grep -Fq 'Unknown photo candidate: DoesNotExist' "$work/missing.out"

printf 'Photo candidate installer tests passed.\n'
