# Clean macOS native preview bootstrap · #149

Base main `f683c29`; implementation and actual workflow tested at
`2e007138336f9cade4f633c76320a78f5a1da9ce` on Apple M1/macOS 27.3 arm64.
This closes the existing-native-install prerequisite for the recorded preview
workflow. Existing compatible Python/macOS and prepared input caches are still
prerequisites; human quality, physical mobile and final release gates remain open.

## Fixed criterion and chosen path

#149 records the criterion: verify the exact tagged runtime archives and selected
executables, retain notices, publish a wholly new isolated runtime home, stage only
the cleared RealeSR model and run real import → preset → regions → export. Never
overwrite the owner's normal runtime or certify quality from a successful install.

The historical macOS installer assumes a runtime directory and also copies the
unresolved DF2K model. The existing model-add cache preparation path rejected an
empty isolated home because no runtime was installed. The new explicit preview
path avoids that circular prerequisite: prepare the two pinned model files from
the catalog's exact Hugging Face revision, verify their hashes, then stage native
executables and the cleared model together. The historical route is not silently
rewritten or treated as the verified preview route. See [instructions](../../NATIVE_PREVIEW.md).

## Input identity and notices

All downloads were free, from the existing pinned primary sources; the bootstrap
itself reads local files and executes no native code.

| Input | SHA256 |
| --- | --- |
| RealSR 20220728 macOS archive, 69,621,461 bytes | b4bb7a55508a65091aedcbdc3e942b1b4779a71baba29c2e2175e02d41ddf1d6 |
| Selected RealSR executable | 4daca3d6c89f7e24f7fb10a8584cefeccceac0811413908f57e53f724fb86fb0 |
| Real-ESRGAN 20220424 macOS archive, 51,817,124 bytes | e0ad05580abfeb25f8d8fb55aaf7bedf552c375b5b4d9bd3c8d59764d2cc333a |
| Selected Real-ESRGAN executable | c1c35d92079085de96b9d547fd7e4464bc8a2e9ccf28d7b8c712d72ade91b7cc |
| RealSR embedded MIT notice | 57157b0fc6954dd1645dc674cc99bebbab4cb84c5b306b910989777e3d0d6fbd |
| Real-ESRGAN tagged BSD notice | 4a699ec4863d96a91fc265948a0c90033f7e8735d515524dcf3444736406e0c2 |

The Real-ESRGAN archive contains no notice member; its source `v0.2.5.0` tag was
resolved to commit `685d429c81888252bdb10f56c7754baededc3823`, and that exact
`LICENSE` was saved. Runtime notices are now source-packaged and digest-bound.
The runtime catalog's archive hashes are populated, status uses the existing
`pinned_sha256` contract, and the Real-ESRGAN executable path reflects the actual
`realesrgan-binary` installation name.

Freshly downloaded RealeSR-general-v3 cache, source revision
`0fe68041370150c7695816e229dc982bfc06ed58`:
`x4.param` SHA256 `ce766e261369b911c3f3f607266380e6e6133e82699fed5e3b3afa07482c34c1`;
`x4.bin` SHA256 `01450f4a79b81c0f1f3eeefc31121167886125c25e41a6d4773e8ec8062528a1`.
The pre-existing cleared model terms and quality-certification state are unchanged.
The packaged model notice is now pinned to
`5db8ca648f040893303f15bed1e3741b64723912275c087d56614f82d1fc6777`.

## Implementation and review correction

`bootstrap-macos-preview.py` / `native_preview.py` verifies whole archives, reads
only the selected regular ZIP members, verifies executable/notice bytes, stages
models through the existing cleared-model gate and registers their weight hashes.
It publishes a new complete home with Darwin `renamex_np(RENAME_EXCL)`, checked
against the Apple SDK definition and exercised on the actual host. Even a
concurrently created empty target is preserved. Failed attempts remove only their
own unpublished staging directory. No arbitrary ZIP tree is extracted.

The preview dispatcher accepts only the staged RealeSR model at 4×, quotes paths
and removes temporary model aliases after native success or failure.

Independent review reproduced a model-notice gap in shared `stage_models`: a
symlink could supply outside, non-license bytes. Fixed that shared boundary to
reject unsafe/outside/symlink notices, require their pinned digest and check the
copied bytes. Re-review confirmed the reproducer now publishes nothing, even when
outside bytes match the expected notice. This strengthens notice integrity without
changing commercial eligibility or image acceptance criteria.

## Actual clean archive and full workflow

Built and audited source previews from clean implementation `2e00713`:

| Archive | SHA256 |
| --- | --- |
| fidelis-local-preview-2e007138336f.tar.gz | df2aa8b2e802b74d48b36b6620000d604d92c0bc4e79555591f69ce0621e8838 |
| fidelis-local-preview-2e007138336f.zip | d791fcba48d3f6ef5351b47813acbaaa454367ff5b14cca4713f71e9b443796d |

Extracted into a new directory, ran the packaged native bootstrap into a previously
nonexistent home and installed the 22 locked Python wheels with the packaged offline
installer. No previously installed Fidelis native runtime/model home was used.
Only RealeSR-general-v3 was installed; DF2K is absent. The provenance auditor reports
both selected native executables and the model as `matched`.

Started the extracted application at `127.0.0.1:18951`, pointing only to that new
runtime home. Actual `Fast_Fidelity` / RealeSR NCNN inference, `luxury_apparel`
region protection/reblend and revision-2 export completed:

- Approved diagnostic source mel014, 331×494 → **1324×1976** output.
- **588,000 protected pixels**, **zero mismatches** against the separate base.
- Preset request **5.638 s**; complete API workflow **7.261 s**, one run.
- Separate preset/base/export hashes match the earlier verified workflows;
  protected export SHA256
  `53223189fc7621622999282995df9ecf41b87ca973050e67647d59bba1791007`.
- Server stopped after verification. The normal owner runtime was not changed.

Private evidence:
`~/melato-corpus/fidelis/release-evidence/2e00713-native-preview/` contains archives,
`preview-receipt.json`, `bootstrap-stdout.json`, new `runtime-home/`, extracted
application/install log, `model-runtime-audit.json`, reproduction script,
`workflow-receipt.json` and separate `outputs/` PNGs. Bootstrap receipt SHA256
`4481e81bcc22fd75fdd4a071e1593fe9e38df676a010c009217f5cbbf24f309a`;
workflow receipt SHA256
`f607bd5992c21830d628f2a5878246da53c2fa898233f8f4dcdd15d0f4afde8c`.
Archive/notice/model download receipts are in the sibling
`native-runtime-archives-20261128/` collection. Preparation used downloads; system
networking was not disabled. Byte-staging receipts deliberately retain
`native_execution_verified: false`; separate actual workflow evidence establishes
this execution without rewriting the original staging claim.

## Validation and remaining gates

Fifteen native/bootstrap dispatcher regressions, ten model-provenance tests, one
model-redistribution test and seven release-packaging tests pass. Coverage includes
hash/notice/model failures, confined paths, unsafe ZIP entries, atomic publication,
concurrent destinations, wrapper quoting/cleanup and retained existing homes.
The negative provenance fixture explicitly sets a missing archive hash rather than
depending on the old production catalog's null value; its rejection assertion is
unchanged. Syntax/import lint and diff checks pass. CI runs the new regressions;
source packages require the helper, dispatcher, tests, instructions and notices.

This is a repeatable macOS arm64 preview bootstrap from prepared artifacts and
existing compatible Python/OS. It is not a Python/OS installer, universal platform
bundle, SDXL qualification, human/device or image-quality signoff. The official
release manifest remains historical. Corpus/source exposure, representative quality,
blind review, physical mobile and final creative/release decisions remain open.
