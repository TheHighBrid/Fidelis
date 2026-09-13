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
grep -q 'SDPA kernel probe' "$repo_root/notebooks/Fidelis_VOSR2_Colab.ipynb"
grep -q 'torch==2.13.0' "$repo_root/notebooks/Fidelis_VOSR2_Colab.ipynb"
grep -q 'https://download.pytorch.org/whl/cu130' "$repo_root/notebooks/Fidelis_VOSR2_Colab.ipynb"
grep -q 'huggingface_hub==1.31.0' "$repo_root/notebooks/Fidelis_VOSR2_Colab.ipynb"
grep -q "protected = {'torch', 'torchvision', 'torchaudio', 'transformers'}" "$repo_root/notebooks/Fidelis_VOSR2_Colab.ipynb"
if grep -q 'huggingface_hub>=0.34,<1' "$repo_root/notebooks/Fidelis_VOSR2_Colab.ipynb"; then
  printf 'Obsolete Hugging Face pin is still present.\n' >&2
  exit 1
fi

printf 'Static smoke tests passed.\n'
