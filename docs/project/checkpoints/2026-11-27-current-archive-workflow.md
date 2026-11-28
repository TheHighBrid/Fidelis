# Current archive, fresh environment and real local workflow · #145

Source: `8d621e2694af46aa8a0f3100f4d76d562683acb2`, after #138–#144.
Executed 2026-11-27 America/Toronto (2026-11-28 UTC) on Apple M1/macOS arm64.
The older local raw-checkpoint prototype was preserved at local `ce950d6`,
not merged: #138 already implements the successor workflow. No candidate pixels,
criteria, source splits or runtime code were changed for this check.

## Fixed criterion and actual result

Build and audit a committed source preview, extract it into a new directory,
create a fresh Python environment, install the onboarding dependencies, start a
loopback-only service, then perform actual import → supported preset → region
protection/reblend → export. Preserve separate full-resolution files and compare
every fully protected pixel exactly to the precision base. This is API workflow
evidence, not physical gestures, visual approval or an untouched held-out study.

`scripts/package-local-preview.sh` built and audited both source archives:

| Artifact | SHA256 |
| --- | --- |
| fidelis-local-preview-8d621e2694af.tar.gz | 2cba0ac0b5e07d85b6717623ea9d45063ffe9b51400267f18e44f745624ed19f |
| fidelis-local-preview-8d621e2694af.zip | 7e6f0c447cfe5361bcf1e6c68db6b124317fea9e793098639a828ae720647c2b |

Fresh CPython 3.12.16 environment in the extracted archive; installed onboarding
packages through `uv pip install`: Pillow 13.0.0, NumPy 2.5.5, SciPy 1.18.1,
scikit-image 0.26.0, OpenCV headless 5.1.0.95, PyYAML 6.0.4, pytest 9.2.0,
httpx 0.28.1 and their resolved dependencies. An initial cache-only install failed
because required packages were unavailable locally; free registry downloads then
completed. This is **not a disconnected installation**. The existing local NCNN
executable/model installation was reused, rather than claiming a fresh runtime
or weight installation. Preview archives bundle neither.

Actual HTTP service bound to `127.0.0.1:18947`, then stopped after verification:

1. Imported approved calibration/diagnostic source `mel_014`, 331×494 RGB,
   SHA256 `bd1249a6e7ea02a231d199035a578d1b391815f8e57389aec2de1c28ebacb91b`.
2. Ran `Fast_Fidelity`, real `RealeSR-general-v3` NCNN, text preservation and
   wavelet colour setting; output 1324×1976. Preset request: **4.862 s**.
3. Imported aligned preset output and a separate 4× bicubic base with explicit
   confidence/protection/fabric masks; selected `luxury_apparel`.
4. Reblended fabric at 0.6 with skin/hair zero; saved revision 2 and exported PNG.
5. All **588,000** fully protected pixels matched the base, **zero mismatches**.
   Complete API workflow: **6.817 s**, single run, not an inference-only benchmark.

Separate artifacts:

| File | Bytes | SHA256 |
| --- | ---: | --- |
| preset-output.png | 2061765 | 80a9b907f86ab139a3129cdbe90e894efd8da89b69d0de0913defc3ccddeb8d5 |
| bicubic-base.png | 1069009 | 52cb398e38077fda6c942891d50d5793a292f9218751d8f9efe057dbbdb1d3d1 |
| protected-export.png | 2267597 | 53223189fc7621622999282995df9ecf41b87ca973050e67647d59bba1791007 |

The export hash matches the historical `c04aeb2` clean API check exactly. This is
repeatability for these specific pixels/settings, not general image quality.

Model `.param` SHA256 `ce766e261369b911c3f3f607266380e6e6133e82699fed5e3b3afa07482c34c1`;
`.bin` SHA256 `01450f4a79b81c0f1f3eeefc31121167886125c25e41a6d4773e8ec8062528a1`.
The installed dispatcher selects `realesrgan-binary` for this compact model;
actual binary SHA256 `c1c35d92079085de96b9d547fd7e4464bc8a2e9ccf28d7b8c712d72ade91b7cc`.

## Evidence location and remaining limits

Private root: `~/melato-corpus/fidelis/release-evidence/8d621e2-clean-preview/`.
It contains `preview-receipt.json`, `workflow-receipt.json`,
`runtime-model-hashes.json`, `verify_clean_workflow.py`, the two audited archives,
the extracted application/fresh environment and `outputs/` with separate PNGs.
No source image binaries are committed. Checks: actual workflow above, archive
audits, project JSON parsing and `git diff --check`.

The application still takes aligned base/texture passes for region controls;
this check does not imply a new one-click regional inference interface. Source
mel014 has known calibration exposure and is not used here to certify held-out
quality. The official package manifest remains historical `86c4f86d`; preview
hashes do not replace it. A final frozen RC, dependency/runtime offline bundle,
full representative quality evidence, remaining corpus/source-exposure resolution,
physical-device checks and creative/release approval remain open. Continue these
independent tasks before escalating individual owner decisions.
