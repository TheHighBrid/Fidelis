#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
cli="$repo_root/bin/fidelis"
work="$(mktemp -d "${TMPDIR:-/tmp}/fidelis-batch-audition-test.XXXXXX")"
trap 'rm -rf "$work"' EXIT

export FIDELIS_HOME="$work/home"
runtime="$FIDELIS_HOME/runtime"
mkdir -p "$runtime"

for model in PhotoA PhotoB; do
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

in_dir="$work/input_shoot"
mkdir -p "$in_dir"
printf 'image1\n' > "$in_dir/shot1.png"
printf 'image2\n' > "$in_dir/shot2.jpg"

out_dir="$work/lookbook_results"

bash "$cli" batch-audition "$in_dir" "$out_dir" PhotoA PhotoB

test -d "$out_dir/auditions/audition_shot1"
test -d "$out_dir/auditions/audition_shot2"
test -s "$out_dir/auditions/audition_shot1/manifest.json"
test -s "$out_dir/auditions/audition_shot2/manifest.json"
test -s "$out_dir/lookbook.html"

grep -Fq 'Fidelis Editorial Lookbook Audition' "$out_dir/lookbook.html"
grep -Fq 'PhotoA' "$out_dir/lookbook.html"
grep -Fq 'PhotoB' "$out_dir/lookbook.html"

printf 'Batch audition & lookbook generation tests passed.\n'
