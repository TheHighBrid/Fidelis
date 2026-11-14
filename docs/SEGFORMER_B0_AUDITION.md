# SegFormer B0 local audition

The optional `propose` command runs the pinned Xenova SegFormer B0 ONNX export on the saved base and stages a mask suggestion for review in Studio. It checks the weight bytes before creating a CPU session. Accept or discard the proposal from the existing review panel.

## Run locally

Install ONNX Runtime in the Fidelis virtual environment. The Linux x86-64 audition used version 1.31.1.

```bash
.venv/bin/python -m pip install onnxruntime
curl -fL 'https://huggingface.co/Xenova/segformer_b0_clothes/resolve/a2489ea8e7ec1ee912190546bad31a4906ccca76/onnx/model.onnx' -o segformer-b0-clothes.onnx
.venv/bin/python scripts/mask-suggestion.py propose --workspace WORKSPACE --job JOB_ID \
  --expected-revision SAVED_REVISION --weights segformer-b0-clothes.onnx
```

The expected SHA-256 is `02e6f1545475bc549184b6710487555b4b73eb08354cc3a480fb4fab1473a9d3`. The pinned processor specifies a 512 × 512 RGB bilinear resize and ImageNet channel normalization. The CPU session returned float32 logits with shape `1 × 18 × 128 × 128`. Both pinned configs agree on all 18 labels. Routing proposes Hair and four garment labels. Face, limbs, accessories and the remaining classes route to unknown. The current confidence, ambiguity and boundary defaults apply.

- [Pinned export and processor](https://huggingface.co/Xenova/segformer_b0_clothes/tree/a2489ea8e7ec1ee912190546bad31a4906ccca76)
- [Pinned original checkpoint card and config](https://huggingface.co/mattmdjaga/segformer_b0_clothes/tree/7142c7f9d2be9ee39a47bd2091ad9d5fbe61bb1b)

## Photo smoke test

The test used the 512 × 512 scikit-image astronaut sample from v0.25.2. Its PNG SHA-256 was `88431cd9653ccd539741b555fb0a46b61558b301d4110412b5bc28b5e3ea6cb5`. The scikit-image documentation identifies it as public-domain NASA photography. The checked-in benchmark corpus remains subject to its existing selection and review process. [Sample documentation](https://scikit-image.org/docs/0.25.x/api/skimage.data.html#skimage.data.astronaut)

| Hand-selected region | Rectangle x, y, width, height | Pixels with proposed texture confidence |
| --- | --- | --- |
| Hair | 180, 37, 75, 30 | 2,058 / 2,250 |
| Face | 183, 94, 75, 65 | 0 / 4,875 |
| Garment panel | 90, 301, 25, 35 | 875 / 875 |
| Suit patch | 130, 348, 75, 65 | 3,611 / 4,875 |
| Zipper | 241, 323, 13, 122 | 156 / 1,586 |
| Helmet | 320, 405, 130, 85 | 0 / 11,050 |

Staging preserved the master hash. A manual lock on the patch preserved all 4,875 patch pixels exactly after accepting the proposal against a deliberately different texture pass. Session creation took about 0.15 s and inference about 0.30 s with two intra-op threads in one Linux x86-64 run.

## Apple M1 (`Darwin arm64`, 8 GB unified memory) target-device benchmark · 2026-11-13

Executed on Apple M1 (`Darwin 25.4.0 arm64`, 8 GB unified memory) with `onnxruntime 1.32.0` (`CPUExecutionProvider`, 2 intra-op threads) and the pinned `Xenova/segformer_b0_clothes` ONNX weights (`~/.local/share/fidelis/models/segmentation/model.onnx`, SHA-256 `02e6f1545475bc549184b6710487555b4b73eb08354cc3a480fb4fab1473a9d3`) via `scripts/mask-suggestion.py propose` under `/usr/bin/time -l`:

| Job / Input | Full-Resolution Grid | Session Creation (`s`) | ONNX Inference (`s`) | Total CLI + Stripe Upsample (`s`) | Peak RSS (`MB`) |
| :--- | :---: | ---: | ---: | ---: | ---: |
| `astronaut_512` (`luxury_apparel`) | `512 × 512` (0.26 MP) | `0.0902` | `0.1923` | `0.5339` | `292.06` |
| `portrait_skin_600` (`editorial_skin`) | `600 × 600` (0.36 MP) | `0.0497` | `0.1708` | `0.4426` | `294.27` |
| `fashion_fabric_800` (`luxury_apparel`) | `800 × 800` (0.64 MP) | `0.0462` | `0.1706` | `0.4557` | `302.70` |
| `astronaut_2048` (`luxury_apparel`) | `2048 × 2048` (4.19 MP) | `0.0486` | `0.1697` | `0.8317` | `378.88` |

The Apple M1 run reproduced identical ROI proposal pixel counts on `astronaut_512` (`Hair 2,058 / 2,250`, `Face 0 / 4,875`, `Garment panel 875 / 875`, `Suit patch 3,611 / 4,875`, `Zipper 156 / 1,586`, `Helmet 0 / 11,050`) and completed 4.2 MP (`2048 × 2048`) full-resolution stripe refinement in `0.83 s` at `378.88 MB` peak RSS. Accuracy across a broader annotated garment corpus and commercial rights clearance still need verification.

## Qualification status

The original B0 card declares MIT and identifies ATR training data. The Xenova card identifies the ONNX conversion and omits a separate license declaration. The ATR repository requests citations for academic and commercial research. The hosted dataset card leaves licensing information unfilled. Production rights review remains open. [Original card](https://huggingface.co/mattmdjaga/segformer_b0_clothes/blob/7142c7f9d2be9ee39a47bd2091ad9d5fbe61bb1b/README.md) · [Converted card](https://huggingface.co/Xenova/segformer_b0_clothes/blob/a2489ea8e7ec1ee912190546bad31a4906ccca76/README.md) · [ATR project](https://github.com/lemondan/HumanParsing-Dataset) · [Dataset card](https://huggingface.co/datasets/mattmdjaga/human_parsing_dataset)

F09 remains partial. The patch and zipper coverage makes the candidate unsuitable for unattended application. F10 needs structural protection evidence, and F09 needs a broader annotated accuracy set and target-device runs.
