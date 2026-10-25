#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
benchmark="$repo_root/scripts/benchmark-photo-candidates.sh"
installer="$repo_root/scripts/install-photo-candidate.sh"
work="$(mktemp -d "${TMPDIR:-/tmp}/fidelis-photo-benchmark-test.XXXXXX")"
trap 'rm -rf "$work"' EXIT

export FIDELIS_HOME="$work/home"
runtime="$FIDELIS_HOME/runtime"
mkdir -p "$runtime/models-ESRGAN-Nomos8kSC"
printf 'nomos-param\n' > "$runtime/models-ESRGAN-Nomos8kSC/x4.param"
printf 'nomos-bin\n' > "$runtime/models-ESRGAN-Nomos8kSC/x4.bin"

export FIDELIS_ENGINE_LOG="$work/engine.log"
cat > "$runtime/realsr-ncnn" <<'SH'
#!/usr/bin/env bash
set -Eeuo pipefail
input='' output='' model=''
while [[ $# -gt 0 ]]; do
  case "$1" in
    -i) input="$2"; shift 2 ;;
    -o) output="$2"; shift 2 ;;
    -m) model="$2"; shift 2 ;;
    -s|-t) shift 2 ;;
    -h) printf 'fake realsr\n'; exit 0 ;;
    *) shift ;;
  esac
done
printf '%s|%s|%s\n' "$input" "$output" "$model" >> "$FIDELIS_ENGINE_LOG"
if [[ -n "${FIDELIS_FAIL_MODEL:-}" && "$(basename "$model")" == "models-$FIDELIS_FAIL_MODEL" ]]; then
  exit 0
fi
mkdir -p "$(dirname "$output")"
printf 'fake image from %s\n' "$(basename "$model")" > "$output"
SH
chmod +x "$runtime/realsr-ncnn"

cli_wrapper="$work/fidelis"
cat > "$cli_wrapper" <<SH
#!/usr/bin/env bash
exec bash "$repo_root/bin/fidelis" "\$@"
SH
chmod +x "$cli_wrapper"
export FIDELIS_CLI="$cli_wrapper"
export FIDELIS_CANDIDATE_INSTALLER="$installer"

revision="test-revision"
folder="models-RealeSR-general-v3"
source_dir="$work/source/$revision/$folder"
mkdir -p "$source_dir"
printf 'candidate-param\n' > "$source_dir/x4.param"
printf 'candidate-bin\n' > "$source_dir/x4.bin"
param_sha="$(sha256sum "$source_dir/x4.param" | awk '{print $1}')"
bin_sha="$(sha256sum "$source_dir/x4.bin" | awk '{print $1}')"

catalog="$work/catalog.tsv"
printf '# name\trole\trevision\tfolder\tparam_sha256\tbin_sha256\tlicense_note\n' > "$catalog"
printf 'RealeSR-general-v3\tmobile-general\t%s\t%s\t%s\t%s\tTest license note\n' \
  "$revision" "$folder" "$param_sha" "$bin_sha" >> "$catalog"
export FIDELIS_CANDIDATE_CATALOG="$catalog"
export FIDELIS_CANDIDATE_SOURCE_ROOT="file://$work/source"
export FIDELIS_CANDIDATE_URL_SUFFIX=""

input="$work/input.jpg"
printf 'benchmark-source\n' > "$input"
output_dir="$work/results"

bash "$benchmark" "$input" "$output_dir"

[[ -s "$output_dir/RealeSR-general-v3.png" ]]
[[ -s "$output_dir/ESRGAN-Nomos8kSC.png" ]]
[[ -s "$output_dir/benchmark.json" ]]
[[ -s "$runtime/models-RealeSR-general-v3/fidelis-model.json" ]]
[[ "$(wc -l < "$FIDELIS_ENGINE_LOG")" -eq 2 ]]

input_sha="$(sha256sum "$input" | awk '{print $1}')"
engine_sha="$(sha256sum "$runtime/realsr-ncnn" | awk '{print $1}')"
jq -e \
  --arg input_sha "$input_sha" \
  --arg engine_sha "$engine_sha" \
  '.schema_version == 1
   and .command == "benchmark-photo-candidates"
   and (.host.architecture | length) > 0
   and (.host.kernel | length) > 0
   and .input.sha256 == $input_sha
   and .engine.sha256 == $engine_sha
   and .engine.scale == 4
   and .engine.tile == 256
   and .runtime.total_elapsed_ms >= 0
   and (.models | length) == 2
   and ([.models[].model.name] | sort) == ["ESRGAN-Nomos8kSC","RealeSR-general-v3"]
   and all(.models[]; .runtime.elapsed_ms >= 0 and .output.bytes > 0 and ((.output.sha256 | length) == 64))' \
  "$output_dir/benchmark.json" >/dev/null

jq -e \
  '.source.type == "pinned-remote"
   and .candidate.role == "mobile-general"
   and .candidate.license_note == "Test license note"' \
  "$runtime/models-RealeSR-general-v3/fidelis-model.json" >/dev/null

# A rerun that silently produces no output must invalidate the old evidence and
# fail even when the engine exits with status zero.
export FIDELIS_FAIL_MODEL=ESRGAN-Nomos8kSC
set +e
bash "$benchmark" "$input" "$output_dir" ESRGAN-Nomos8kSC >"$work/fake-success.out" 2>&1
rc=$?
set -e
unset FIDELIS_FAIL_MODEL
[[ $rc -ne 0 ]]
[[ ! -e "$output_dir/benchmark.json" ]]
[[ ! -e "$output_dir/ESRGAN-Nomos8kSC.png" ]]
grep -Fq 'produced no non-empty output' "$work/fake-success.out"

printf 'Photo candidate benchmark tests passed.\n'
