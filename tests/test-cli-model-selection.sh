#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
cli="$repo_root/bin/fidelis"
work="$(mktemp -d "${TMPDIR:-/tmp}/fidelis-cli-test.XXXXXX")"
trap 'rm -rf "$work"' EXIT

export FIDELIS_HOME="$work/home"
runtime="$FIDELIS_HOME/runtime"
mkdir -p "$runtime"

for model in ESRGAN-Nomos8kSC PhotoA PhotoB; do
  mkdir -p "$runtime/models-$model"
  printf 'param-%s\n' "$model" > "$runtime/models-$model/x4.param"
  printf 'bin-%s\n' "$model" > "$runtime/models-$model/x4.bin"
done

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
mkdir -p "$(dirname "$output")"
printf 'fake image from %s\n' "$(basename "$model")" > "$output"
SH
chmod +x "$runtime/realsr-ncnn"

input="$work/input.jpg"
printf 'source\n' > "$input"

models_output="$(bash "$cli" models)"
expected=$'ESRGAN-Nomos8kSC\nPhotoA\nPhotoB'
[[ "$models_output" == "$expected" ]] || {
  printf 'unexpected model list:\n%s\n' "$models_output" >&2
  exit 1
}

# Legacy bundled models must remain inspectable even without registry metadata.
legacy_info="$(bash "$cli" model-info PhotoA)"
printf '%s' "$legacy_info" | jq -e '.name == "PhotoA" and .registry == "legacy-unregistered" and .scale == 4' >/dev/null

# Add a converted candidate atomically and verify provenance metadata.
new_param="$work/candidate.param"
new_bin="$work/candidate.bin"
printf 'candidate-param-v1\n' > "$new_param"
printf 'candidate-bin-v1\n' > "$new_bin"
expected_param_sha="$(sha256sum "$new_param" | awk '{print $1}')"
expected_bin_sha="$(sha256sum "$new_bin" | awk '{print $1}')"

bash "$cli" model-add PhotoCandidate "$new_param" "$new_bin"
[[ -s "$runtime/models-PhotoCandidate/x4.param" ]]
[[ -s "$runtime/models-PhotoCandidate/x4.bin" ]]
[[ -s "$runtime/models-PhotoCandidate/fidelis-model.json" ]]

candidate_info="$(bash "$cli" model-info PhotoCandidate)"
printf '%s' "$candidate_info" | jq -e \
  --arg p "$expected_param_sha" --arg b "$expected_bin_sha" \
  '.schema_version == 1 and .name == "PhotoCandidate" and .engine == "realsr-ncnn" and .format == "ncnn" and .scale == 4 and .sha256.param == $p and .sha256.bin == $b' >/dev/null

# Duplicate add is rejected and leaves the registered model untouched.
set +e
bash "$cli" model-add PhotoCandidate "$new_param" "$new_bin" >"$work/duplicate.out" 2>&1
rc=$?
set -e
[[ $rc -ne 0 ]]
grep -Fq 'Model already exists: PhotoCandidate' "$work/duplicate.out"
[[ "$(sha256sum "$runtime/models-PhotoCandidate/x4.bin" | awk '{print $1}')" == "$expected_bin_sha" ]]

# Explicit replacement swaps the model and metadata together.
printf 'candidate-param-v2\n' > "$new_param"
printf 'candidate-bin-v2\n' > "$new_bin"
replacement_bin_sha="$(sha256sum "$new_bin" | awk '{print $1}')"
bash "$cli" model-add PhotoCandidate "$new_param" "$new_bin" --replace
replacement_info="$(bash "$cli" model-info PhotoCandidate)"
printf '%s' "$replacement_info" | jq -e --arg b "$replacement_bin_sha" '.sha256.bin == $b' >/dev/null

# Unsafe names never reach the filesystem.
set +e
bash "$cli" model-add '../escape' "$new_param" "$new_bin" >"$work/unsafe.out" 2>&1
rc=$?
set -e
[[ $rc -ne 0 ]]
grep -Fq 'Invalid model name' "$work/unsafe.out"

bash "$cli" upscale "$input" "$work/default.png"
grep -Fq "$runtime/models-ESRGAN-Nomos8kSC" "$FIDELIS_ENGINE_LOG"

after_default="$(wc -l < "$FIDELIS_ENGINE_LOG")"
[[ "$after_default" -eq 1 ]]

bash "$cli" upscale "$input" "$work/a.png" --model PhotoA
tail -n 1 "$FIDELIS_ENGINE_LOG" | grep -Fq "$runtime/models-PhotoA"

FIDELIS_MODEL=PhotoB bash "$cli" upscale "$input" "$work/b.png"
tail -n 1 "$FIDELIS_ENGINE_LOG" | grep -Fq "$runtime/models-PhotoB"

: > "$FIDELIS_ENGINE_LOG"
bash "$cli" audition "$input" "$work/audition"
[[ -s "$work/audition/ESRGAN-Nomos8kSC.png" ]]
[[ -s "$work/audition/PhotoA.png" ]]
[[ -s "$work/audition/PhotoB.png" ]]
[[ -s "$work/audition/PhotoCandidate.png" ]]
[[ -s "$work/audition/manifest.json" ]]
[[ "$(wc -l < "$FIDELIS_ENGINE_LOG")" -eq 4 ]]

input_sha="$(sha256sum "$input" | awk '{print $1}')"
engine_sha="$(sha256sum "$runtime/realsr-ncnn" | awk '{print $1}')"
jq -e \
  --arg input_sha "$input_sha" \
  --arg engine_sha "$engine_sha" \
  '.schema_version == 1
   and .command == "fidelis audition"
   and .input.sha256 == $input_sha
   and .engine.name == "realsr-ncnn"
   and .engine.sha256 == $engine_sha
   and (.models | length) == 4
   and ([.models[].model.name] | sort) == ["ESRGAN-Nomos8kSC","PhotoA","PhotoB","PhotoCandidate"]
   and all(.models[]; (.output.bytes > 0) and ((.output.sha256 | length) == 64))' \
  "$work/audition/manifest.json" >/dev/null

: > "$FIDELIS_ENGINE_LOG"
bash "$cli" audition "$input" "$work/subset" PhotoCandidate PhotoA
[[ -s "$work/subset/PhotoA.png" ]]
[[ -s "$work/subset/PhotoCandidate.png" ]]
[[ ! -e "$work/subset/ESRGAN-Nomos8kSC.png" ]]
[[ -s "$work/subset/manifest.json" ]]
[[ "$(wc -l < "$FIDELIS_ENGINE_LOG")" -eq 2 ]]
jq -e \
  '(.models | length) == 2
   and ([.models[].model.name] | sort) == ["PhotoA","PhotoCandidate"]' \
  "$work/subset/manifest.json" >/dev/null

# Registered files are immutable evidence. Manual mutation must invalidate the
# registry rather than silently producing a misleading audition manifest.
printf 'tampered-bin\n' > "$runtime/models-PhotoCandidate/x4.bin"
set +e
bash "$cli" model-info PhotoCandidate >"$work/tamper-info.out" 2>&1
rc=$?
set -e
[[ $rc -ne 0 ]]
grep -Fq 'Model integrity mismatch: PhotoCandidate' "$work/tamper-info.out"

set +e
bash "$cli" audition "$input" "$work/tampered-audition" PhotoCandidate >"$work/tamper-audition.out" 2>&1
rc=$?
set -e
[[ $rc -ne 0 ]]
[[ ! -e "$work/tampered-audition/manifest.json" ]]
grep -Fq 'Model integrity mismatch: PhotoCandidate' "$work/tamper-audition.out"

set +e
bash "$cli" upscale "$input" "$work/missing.png" --model DoesNotExist >"$work/missing.out" 2>&1
rc=$?
set -e
[[ $rc -ne 0 ]]
grep -Fq 'Model is not installed: DoesNotExist' "$work/missing.out"

printf 'CLI model registry, integrity, selection, and audition provenance tests passed.\n'
