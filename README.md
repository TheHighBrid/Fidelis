# Fidelis

Fidelis is a local, ARM64-native image upscaling pipeline for natural fashion and product photography. Its default goal is credible detail, not aggressive sharpening: skin should remain skin, fabric should retain weave, and logos and seams should not be redrawn.

## Current target

- Android 16 / Termux (`aarch64`)
- Snapdragon 8 Gen 2 / Adreno 740
- Turnip/Freedreno Vulkan
- RealSR NCNN Android CLI
- `4xNomos8kSC` photographic model
- Single-image and folder batch processing

## Status

The first milestone is a reproducible CLI installation. The installer downloads the latest ARM64 upstream APK, verifies the release-provided SHA-256 digest, and extracts only its native CLI runtime and bundled models. Large binaries and models are never committed to this repository.

## Install in native Termux

Do not run the installer inside Ubuntu/Debian proot.

```bash
pkg install -y git
git clone https://github.com/TheHighBrid/Fidelis.git
cd Fidelis
./install.sh
```

Restart the shell or run:

```bash
source "$HOME/.profile"
fidelis doctor
```

## Commands

```bash
fidelis doctor
fidelis models
fidelis upscale input.jpg output.png
fidelis batch ./input ./output
```

The raw 4x output is intentional in milestone one. A visually validated natural 2x finishing stage will be added only after testing on one model image and one product image.

## Principles

- Preserve natural tonal texture and edge roll-off.
- Do not enable face restoration by default.
- Keep upstream models and runtimes outside Git.
- Fail clearly when architecture, storage, runtime, or model requirements are not met.
- Pin installed upstream metadata so results can be reproduced.

## Upstream

Fidelis currently wraps the ARM64 runtime from [RealSR-NCNN-Android](https://github.com/tumuyan/RealSR-NCNN-Android). Review its licenses and the license of each selected model before commercial distribution.

