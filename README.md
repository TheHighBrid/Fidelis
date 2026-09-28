# Fidelis

Fidelis is an image-restoration project for natural fashion and product photography. Its standard is **credible photographic detail**, not aggressive sharpening: skin should remain skin, fabric should retain believable weave, and seams, logos, hardware, faces, and geometry should not be redrawn.

## Project direction

Fidelis currently has two deliberately separate lanes:

### 1. ARM64 local runtime lane

Target hardware:

- Android 16 / Termux (`aarch64`)
- Snapdragon 8 Gen 2 / Adreno 740
- Turnip/Freedreno Vulkan
- NCNN/Vulkan inference
- single-image and folder batch processing

The existing RealSR-NCNN Android integration proves that a native ARM64/Vulkan CLI is practical. `4xNomos8kSC` remains a reproducible baseline model, **not the accepted final quality target**. Visual testing showed synthetic/checkerboard-like texture and overprocessed skin/fabric on some photographs, so Fidelis will not optimize around Nomos simply because it runs locally.

The CLI can register compatible NCNN candidates with SHA-256 provenance, verify registered model integrity, select any installed candidate, and audition several models against the exact same source image. Each audition produces standalone PNGs plus a machine-readable evidence manifest, turning local model research into a reproducible comparison instead of a code-editing exercise.

### 2. Quality-reference lane

VOSR is being used as an external quality reference to establish what Fidelis should reproduce before choosing or converting the final local model.

Current experiment:

- official VOSR 1.4B multi-step checkpoint
- fixed seed and 25 steps
- deterministic VAE mode
- wavelet colour alignment
- three controlled fidelity profiles
- no sharpening
- no face restoration
- no source blending
- no synthetic grain
- no secondary SR pass

The previous Fidelis 2.1 source-fusion finishing stage was rejected because it softened useful micro-detail and reduced the value of the VOSR restoration.

## Current quality experiment

The canonical Colab notebook is:

`notebooks/Fidelis_VOSR_MultiStep_Sweep_Colab.ipynb`

It evaluates the same source through:

| Profile | CFG | Weak condition | Intent |
| --- | ---: | ---: | --- |
| Natural | 0.50 | 0.10 | More reconstruction freedom |
| Fidelity | 1.25 | 0.18 | Balance detail recovery and source loyalty |
| Strict | 1.75 | 0.23 | Strong source loyalty |

The sweep script is:

`experiments/vosr-fidelity-sweep.sh`

A run is considered successful only when every profile creates a verified non-empty PNG. Upstream VOSR can catch an image-level exception and still exit with status `0`, so Fidelis never treats the subprocess return code alone as proof of success.

## Quality acceptance gate

A candidate is judged in this order:

1. **Identity and geometry**: faces, hands, body proportions, garment construction, seams, logos and hardware must not drift.
2. **Skin**: recover believable pores and tonal variation without repeated dots, gritty pore synthesis, waxy smoothing or invented blemishes.
3. **Fabric**: weave, rib, denim, leather, velour and knit texture must follow the real folds and material surface rather than forming a repeated enhancement pattern.
4. **Fine edges**: hair and garment edges may become clearer without halos or invented strands.
5. **Tonal realism**: highlights and shadows should remain photographic rather than locally over-contrasted.
6. **Background restraint**: smooth surfaces should stay smooth; new wall/floor texture is a failure.

Sharpness alone never wins a comparison.

## Decision rule

- If a VOSR multi-step profile materially improves skin/fabric realism over the good VOSR 2.0 one-step reference while preserving geometry, it becomes the external Fidelis quality target.
- If multi-step VOSR does not materially beat the one-step reference, stop spending compute on it.
- After the reference is locked, focus engineering effort on the lightest ARM64-compatible model or conversion that reproduces the winning visual behavior.

## Native Termux CLI

The ARM64 foundation remains available:

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

Commands:

```bash
fidelis doctor
fidelis models
fidelis model-add PhotoCandidate ./candidate.param ./candidate.bin
fidelis model-info PhotoCandidate
fidelis upscale input.jpg output.png
fidelis upscale input.jpg output.png --model PhotoCandidate
fidelis batch ./input ./output --model PhotoCandidate
fidelis audition input.jpg ./audition
fidelis audition input.jpg ./audition PhotoCandidateA PhotoCandidateB
```

`fidelis models` prints usable installed model names. The default stays `ESRGAN-Nomos8kSC` for backwards compatibility, but it can be overridden per command with `--model` or for a session with `FIDELIS_MODEL=<name>`.

`fidelis model-add` installs a 4x NCNN candidate atomically and records the SHA-256 hashes of its `x4.param` and `x4.bin` files. `fidelis model-info` verifies those registered hashes against the live files before reporting provenance. If a registered model is changed outside the registry, Fidelis rejects it until it is explicitly re-added.

`fidelis audition` runs one source through every usable installed model, or through an explicit shortlist, and writes one standalone PNG per model into the output folder. It does not create a collage or alter the generated outputs.

A successful audition also writes `manifest.json` containing the exact input hash, local engine hash, each model's provenance, and each output's byte count and SHA-256 hash. Starting a new audition invalidates any previous manifest in that output directory, and a new manifest is published only after every selected model produces a non-empty output. A failed rerun therefore cannot leave an old success manifest behind.

## Curated photo candidates

Fidelis keeps a small checksum-locked candidate catalog in `config/photo-candidates.tsv`. The first shortlist is:

- `RealeSR-general-v3`: mobile/general first priority
- `RealSR-DF2K`: heavier photo-fidelity comparator
- `ESRGAN-Remacri`: balanced community comparator, evaluation-only until its model license is resolved

List them:

```bash
bash scripts/install-photo-candidate.sh list
```

Install the first mobile candidate without hunting for model files manually:

```bash
bash scripts/install-photo-candidate.sh RealeSR-general-v3
```

The installer downloads from an immutable upstream revision, verifies both `x4.param` and `x4.bin` against pinned SHA-256 values, installs through the existing atomic model registry, and records source revision plus candidate role in the model metadata. A checksum mismatch fails before an existing model can be replaced.

### One-command device benchmark

For the actual Android/ARM64 gate, run one source through the first mobile candidate and the Nomos baseline:

```bash
bash scripts/benchmark-photo-candidates.sh source.jpg ./benchmark
```

The benchmark automatically installs a missing curated candidate through the checksum-locked installer, writes one standalone PNG per model, and creates `benchmark.json` with source/engine/model/output hashes, host architecture and kernel, per-model inference time, and total elapsed time.

A failed rerun invalidates the previous benchmark evidence. Even if the underlying engine exits with status `0`, Fidelis refuses success unless every selected model produces a non-empty output.

The research rationale, exact verified hashes, licensing notes, larger benchmark command, and three-class visual protocol are in `docs/PHOTO_MODEL_CANDIDATES.md`.

## Reliability

Fidelis intentionally fails closed around image generation. The repository includes regression coverage for:

- the VOSR case where image processing can fail while the process still exits successfully
- actual weak-conditioning profile injection
- output PNG verification and manifest creation
- local model selection, default-model override, and missing-model rejection
- atomic candidate registration and registered-model integrity verification
- reproducible multi-model audition manifests with input, engine, model, and output hashes
- stale audition manifest invalidation when a rerun fails
- checksum-locked curated model installation and replacement rejection on source tampering
- one-command device benchmark evidence, candidate auto-install, runtime timing, and fake-success rejection

Run locally:

```bash
bash tests/smoke-test.sh
bash tests/test-cli-model-selection.sh
bash tests/test-photo-candidate-installer.sh
bash tests/test-photo-candidate-benchmark.sh
bash tests/test-vosr-sweep.sh
```

GitHub Actions runs these checks on pull requests and `main` updates.

## Principles

- Preserve natural tonal texture and edge roll-off.
- Prefer source fidelity over invented detail.
- Do not enable face restoration by default.
- Do not hide failed inference behind a successful wrapper exit.
- Keep upstream models and runtimes outside Git.
- Pin upstream revisions needed for reproducibility.
- Treat external generative models as quality references until they prove practical for the ARM64 target.

## Upstream projects

The local ARM64 foundation currently wraps the runtime from [RealSR-NCNN-Android](https://github.com/tumuyan/RealSR-NCNN-Android). The quality-reference experiment uses [VOSR](https://github.com/cswry/VOSR). Review upstream licenses and the license of every selected model before commercial distribution.
