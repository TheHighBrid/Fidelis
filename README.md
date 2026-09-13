# Fidelis

Fidelis is a zero-cost image-restoration workflow for natural fashion and product photography. The quality target is believable photographic detail: stable faces, clean black fabric, readable logos, natural skin, and no checkerboard or sharpening grit.

## Current architecture

The first ARM64 NCNN prototype has been retired. Its Nomos8kSC model degraded faces and its Android Vulkan path produced tiled checkerboard corruption on Adreno 740.

Fidelis now uses:

- VOSR 2.0, a one-step 1.4B vision-only restoration model
- Free interactive Google Colab GPU compute
- Android's normal file picker for input and output
- 512-pixel overlapping DiT tiles and 1024-pixel overlapping VAE tiles
- Wavelet color alignment
- Deterministic output from a fixed seed
- A source-aware finishing stage that rejects unsupported generated edges
- A high-quality 2x JPEG delivery instead of the oversized raw 4x PNG

VOSR still reasons internally at 4x. Fidelis 2.1 then uses the original as the structural reference, blends only supported mid- and high-frequency detail, and downsamples to the more credible 2x delivery size. This is designed to protect identity, garment construction, distant subjects, and natural depth of field.

Your Android ARM64 device is the launcher, not the inference server. This is necessary because Pixella-class generative restoration is far beyond what the current mobile NCNN runtime can reproduce reliably.

## Install or update in native Termux

```bash
cd "$HOME/Fidelis"
git pull
./install.sh
```

## Run

```bash
fidelis open
```

This opens the Fidelis notebook. In Colab, choose a GPU runtime, run all cells, select one or more images, and download the finished ZIP when processing completes.

[Open Fidelis in Google Colab](https://colab.research.google.com/github/TheHighBrid/Fidelis/blob/main/notebooks/Fidelis_VOSR2_Colab.ipynb)

## Important limits

Google Colab is free but GPU availability and session limits are not guaranteed. Fidelis uses Colab interactively and does not create a remote API, tunnel, or background service.

Generative restoration reconstructs plausible missing detail. It cannot determine the exact original pore or thread when that information is absent from the source. The source-aware finishing stage reduces unsupported reconstruction, but the benchmark still rejects outputs that visibly alter identity, logos, garment construction, or tonal structure.

## Licensing

- Fidelis code: MIT
- VOSR code: Apache License 2.0
- VOSR checkpoint host listing: Apache License 2.0
- Qwen Image VAE and DINOv2 components retain their upstream terms

Large models are downloaded directly from their upstream host and are never committed to this repository.
