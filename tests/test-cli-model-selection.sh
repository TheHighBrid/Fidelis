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
  printf 'param\n' > "$runtime/models-$model/x4.param"
  printf 'bin\n' > "$runtime/models-$model/x4.bin"
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
[[ "$(wc -l < "$FIDELIS_ENGINE_LOG")" -eq 3 ]]

: > "$FIDELIS_ENGINE_LOG"
bash "$cli" audition "$input" "$work/subset" PhotoB PhotoA
[[ -s "$work/subset/PhotoA.png" ]]
[[ -s "$work/subset/PhotoB.png" ]]
[[ ! -e "$work/subset/ESRGAN-Nomos8kSC.png" ]]
[[ "$(wc -l < "$FIDELIS_ENGINE_LOG")" -eq 2 ]]

set +e
bash "$cli" upscale "$input" "$work/missing.png" --model DoesNotExist >"$work/missing.out" 2>&1
rc=$?
set -e
[[ $rc -ne 0 ]]
grep -Fq 'Model is not installed: DoesNotExist' "$work/missing.out"

printf 'CLI model-selection tests passed.\n'
