# Clean archive, real preset and protected export

Archive source: `c04aeb2365a6155c49bc7175a78bbc2b17d108d6` (PR #107).
Device: Apple M1, macOS arm64; fresh Python 3.12 environment in extracted archive.
Installed documented scientific dependencies and httpx 0.28.1.

Tar SHA256: `7c3d9ce9ed33223ed1d840ca0e2f79fc058f2ef2c433ce65c60fa2434f772f7b`.
ZIP SHA256: `27be7ddbadbaec0edb257b1f8541aee064f6ebad33a760f6a254b2ddb52a3af9`.
Archive audit passed: 445 members; no missing required or forbidden paths.
These are source-archive results; an offline model bundle remains separate.

Actual HTTP flow on localhost in the extracted application:

1. Import approved calibration photograph mel_014 (331×494).
2. Apply `Fast_Fidelity` with installed real `RealeSR-general-v3` NCNN model,
   text preservation and wavelet colour setting; output 1324×1976.
3. Import that output as texture alongside a separately created 4× bicubic
   precision base; choose `luxury_apparel`, explicit confidence, face protection
   and a narrow shirt fabric mask. This workflow still requires aligned passes.
4. Reblend fabric at 0.6, skin/hair at zero, save revision 2 and export PNG.
5. Compare decoded export against base: all 588,000 protected pixels equal,
   zero protected mismatches. Export SHA256:
   `53223189fc7621622999282995df9ecf41b87ca973050e67647d59bba1791007`.

Off-repo output collection:
`/Users/tyf12/melato-corpus/fidelis/release-evidence/c04aeb2/clean-workflow/`
contains `receipt.json`, `preset-output.png`, `bicubic-base.png`,
`protected-export.png`. Reproduction script is in the adjacent
`d6f420cc/clean-workflow-check.py` evidence collection.

The integration fixture initially failed because a cold startup exceeded its
four-second wait. With a thirty-second readiness allowance the complete HTTP
fixture suite passed; PR #108 carries that bounded test fix.
The actual preset/region/export flow passed after using the documented NPZ keys
`protected` and `confidence`; earlier diagnostic requests missing those keys were
rejected with HTTP 400 before a regional job was created.

This verifies real API operations and separate full-resolution artifacts.
Browser gestures, physical touch ergonomics, human visual acceptance and all
other representative corpus cases remain unverified by this check.
