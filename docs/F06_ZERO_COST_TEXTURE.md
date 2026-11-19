# F06 zero-cost texture qualification: RealeSR-general-v3

Linear: [MEL-60](https://linear.app/melato/issue/MEL-60/f06-qualify-one-live-compatible-texture-workflow).
Workflow: `scripts/qualify-realesr-general-v3.py`.
This note qualifies one pinned NCNN candidate. It does not close M1, and it does not accept image quality.

The candidate is the `RealeSR-general-v3` row in `config/photo-candidates.tsv`:

| Field | Value |
| --- | --- |
| Role | `mobile-general` |
| Revision | `0fe68041370150c7695816e229dc982bfc06ed58` |
| Param SHA-256 | `ce766e261369b911c3f3f607266380e6e6133e82699fed5e3b3afa07482c34c1` |
| Bin SHA-256 | `01450f4a79b81c0f1f3eeefc31121167886125c25e41a6d4773e8ec8062528a1` |
| License note | BSD-3-Clause upstream Real-ESRGAN checkpoint |
| Scale | 4 |

Source of the bytes: `https://huggingface.co/tumuyan2/realsr-models/resolve/0fe68041370150c7695816e229dc982bfc06ed58/models-RealeSR-general-v3/`.
`scripts/install-photo-candidate.sh` downloads that pair, checks both hashes, then calls `fidelis model-add`.

## Contract

- Fully locked pixels (`protect == 1`) are copied from the precision base and stay byte-identical there.
- Partial and unlocked pixels keep the engine output.
- The default precision base is an exact integer repetition of the source: each source pixel becomes a 4×4 block. A `--base` PNG must already be the expected output size.
- An input-sized protect mask is repeated the same way. Any other mask shape stops the run.
- Engine output whose width and height are not `input_width * 4` and `input_height * 4` is discarded. The script does not resize it.
- Inputs are untagged 8-bit RGB PNGs. ICC profiles and non-1 EXIF orientation stop the run.
- One PNG is published, plus a JSON receipt. No grain, sharpening, beauty smoothing, cloud fallback, or paid API is applied.
- A passing receipt is `E1` unless `--record-live` is set and the installed bytes match the committed pin. That case is `E2` for the host that actually ran. `E3` and `E4` are never written.

```bash
.venv/bin/python scripts/qualify-realesr-general-v3.py \
  INPUT.png OUTPUT.png MASK.npz \
  --record-live \
  --receipt OUTPUT.receipt.json
```

Prepare `MASK.npz` from the input grid. This creates a mask; it is not a quality sample:

```bash
.venv/bin/python - <<'PY'
import numpy as np
from PIL import Image
image = Image.open('INPUT.png')
height, width = image.size[1], image.size[0]
protect = np.zeros((height, width), np.float32)
protect[0, 0] = 1  # edit locked source coordinates before the session
np.savez('MASK.npz', protect=protect)
PY
```

## Evidence recorded on this cloud VM

| Level | State |
| --- | --- |
| E0 | The qualifier, fixture tests, and this note exist in the branch. |
| E1 | `tests/test_f06_realesr_qualification.py` passes without the pinned weights. |
| E2 | One Linux x86_64 run of the pinned bytes, described below. |
| E3 | `not_run`. No M1 8GB or Android photograph was reviewed. |
| E4 | `not_run`. This branch is an unmerged draft. |

The Linux run used a synthetic 8×8 RGB PNG, not a photograph. Its output is an integrity record (dimensions, hashes, locked-pixel check). It is not a before/after quality sample and it is not committed.

Receipt fields from that run:

- `evidence_level`: `E2`
- `live_inference`: true
- `e3_visual_device` / `e4_released`: `not_run`
- `hardware`: Linux, `x86_64`, kernel `6.12.113+`; `target_m1_8gb` and `target_android` are `not_run`
- `code_sha`: `1c954cd5d3b949c124b467228669213a50d47355` (base commit; the qualifier was still uncommitted when the process read `git rev-parse HEAD`)
- param / bin SHA-256: the committed pin above, `matches_committed_pin` true
- input 8×8 SHA-256 `b01869bcb9de7df98c765069864952448673838014564bc1f988e4c54d71a8e0`
- output 32×32 SHA-256 `ac676ab719627cea795b5438daeb1175729ba6f90e9c01e6fe22935aa63870a3`, `dimensions_match_scale` true
- protection: pass, 16 locked pixels, 0 changed
- `wall_elapsed_ms`: 455 on this 8×8 input
- `postprocess`: `none`; API fee 0

The NCNN executable was `realesrgan-ncnn-vulkan` from `realesrgan-ncnn-vulkan-20220424-ubuntu.zip` (Real-ESRGAN release `v0.2.5.0`, the Ubuntu asset that matches the macOS release pin in `scripts/install-macos-runtime.sh`). Zip SHA-256 `e5aa6eb131234b87c0c51f82b89390f5e3e642b7b70f2b9bbe95b6a285a40c96`. Binary SHA-256 `22c2296a39b40cc43ac92615c827ab6d4b60b7142e8cee59f718e3f8e2cdbda9`. Verbose output named the Vulkan device `llvmpipe (LLVM 20.1.2, 256 bits)` from Mesa's software Vulkan driver. That is CPU Vulkan on this VM, not an Apple GPU and not an Android GPU.

The local `realsr-ncnn` entry point was a temporary dispatcher, SHA-256 `8db5ed82e1eda30877ac15cc630ed36614f4aa5f2a38795df3b8d24f51e9ad6f`, which copied the pinned `x4.param` / `x4.bin` to `realesr-animevideov3-x4.param` / `realesr-animevideov3-x4.bin` inside a directory whose path contains `models`, then executed that binary with `-n realesr-animevideov3 -s 4`. This is the compact-v3 loader slot already used by `scripts/install-macos-runtime.sh`. The copied bytes still hashed to the committed pin. `realsr-ncnn-vulkan` 20220728 from `nihui/realsr-ncnn-vulkan` rejected the folder name `models-RealeSR-general-v3` with `unknown model dir type`; that binary only recognizes `models-DF2K` and `models-DF2K_JPEG`. The pinned files were not renamed into a DF2K folder.

## Apple Silicon M1 8GB session

Run this on the machine itself. `sysctl` must print `Apple M1` and `8589934592` before the host line is the 8GB M1 target. The receipt can then show `target_m1_8gb: host_reports_m1_8gb` together with `E2`. `e3_visual_device` stays `not_run` until a person reviews real photographs on that machine. Keep those photographs outside this repository until that review exists.

```bash
git clone https://github.com/TheHighBrid/Fidelis.git
cd Fidelis
git checkout work/bot04-f06-zero-cost-texture-20261119
python3 -m venv .venv
.venv/bin/python -m pip install numpy pillow
bash scripts/install-macos-runtime.sh
bash scripts/install-photo-candidate.sh RealeSR-general-v3
sysctl -n machdep.cpu.brand_string
sysctl -n hw.memsize
.venv/bin/python scripts/qualify-realesr-general-v3.py \
  INPUT.png OUTPUT.png MASK.npz \
  --record-live \
  --receipt OUTPUT.receipt.json
```

`install-macos-runtime.sh` refuses to run unless `uname -s` is Darwin. It installs the pinned 20220728 RealSR macOS binary and the 20220424 Real-ESRGAN macOS binary, then writes the `realsr-ncnn` dispatcher.

## Android / Termux session

`./install.sh` requires native aarch64 Termux (`PREFIX=/data/data/com.termux/files/usr`), not proot, and at least 700 MB free. It installs `realsr-ncnn` from the current RealSR-NCNN-Android ARM64 APK after checking that release's SHA-256 digest. The candidate installer then fetches the pinned weights.

```bash
pkg install -y git python
git clone https://github.com/TheHighBrid/Fidelis.git
cd Fidelis
git checkout work/bot04-f06-zero-cost-texture-20261119
./install.sh
bash scripts/install-photo-candidate.sh RealeSR-general-v3
python -m venv .venv
.venv/bin/python -m pip install numpy pillow
.venv/bin/python scripts/qualify-realesr-general-v3.py \
  INPUT.png OUTPUT.png MASK.npz \
  --record-live \
  --receipt OUTPUT.receipt.json
```

If the device pip install cannot build `numpy`, stop and record the installer error. Skipping the protect mask would drop the lock check. A receipt with `target_android: host_reports_android_markers` and `evidence_level: E2` is device inference evidence. Visual acceptance is still a separate review of the output photographs.

## What remains outside this note

M1 8GB and Android have not been run from this VM. Photographic appearance, identity, fabric, and hardware review are E3 work and are not claimed here. `.github/workflows/ci.yml` is unchanged; the fixture tests run with:

```bash
.venv/bin/python -m unittest tests.test_f06_realesr_qualification -v
```
