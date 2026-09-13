#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
bash -n "$repo_root/install.sh"
bash -n "$repo_root/bin/fidelis"
jq empty "$repo_root/notebooks/Fidelis_VOSR2_Colab.ipynb"

grep -q 'VOSR 2.0' "$repo_root/README.md"
grep -q 'legacy_ncnn.*retired' "$repo_root/install.sh"
grep -q 'retired NCNN prototype' "$repo_root/bin/fidelis"
grep -q '516f292b99cf23c76fdc33351e86dc4f97711fe8' "$repo_root/notebooks/Fidelis_VOSR2_Colab.ipynb"
grep -q 'c9450b611e6b0e854212b81fecde2da5d088c1bc' "$repo_root/notebooks/Fidelis_VOSR2_Colab.ipynb"
grep -q 'images_bhwc01=image' "$repo_root/notebooks/Fidelis_VOSR2_Colab.ipynb"
grep -q -- '--lowvram' "$repo_root/notebooks/Fidelis_VOSR2_Colab.ipynb"

printf 'Static smoke tests passed.\n'
