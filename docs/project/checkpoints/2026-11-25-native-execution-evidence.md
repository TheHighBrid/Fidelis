# Native execution, source recovery and split audit · 2026-11-25

Evidence-only follow-up to #133, based on main `5099a7a89fcf107e5b1a6a8a6528e22626f1923e`.
Scope: preserve measured execution and audit findings; do not change pixels,
split assignments, criteria, model eligibility or release approval.

## Integrated numerical correction

#133 merged exact tested head `53f1995619c3c619e05eee20b2046a420bd12072`.
Local full suite: 647 tests passed, four skipped, 127.074 seconds. Web UI and
static smoke passed. Required macOS/Ubuntu CI, report integrity and Codacy passed
on that head. See [precision checkpoint](2026-11-25-weave-precision.md).
The package manifest remains historical `86c4f86d`, `merged_to_main: true`;
those archives do not contain these newer fixes. Rebuild the eventual frozen RC.

## Actual 198.7 MP local inference: output saved, evaluation interrupted

Apple M1 8 GB, explicit MPS, SwinIR-lightweight-DIV2K-x4, tile core 192/context
32, frozen calibration case `tex_cotton_twill_chino`, candidate head `53f1995`.
Model SHA256 `09fad24e32ae62722e1a055efde9921328f4137981bab0a42a4a3a806306c58e`.
Source SHA256 `eca7ad1ab4f540d9efbcd2b37eeb86a705ad8b96be63ba7ed63ce3c6541cc55f`,
4351 × 2854. Output 17404 × 11416 = 198,684,064 pixels; no downsampling.
Source ROI `[653,428,3045,1998]`, target `[2612,1712,12180,7992]`.

Separate PNGs under private root
`~/melato-corpus/fidelis/release-evidence/53f1995/twill-swinir/cases/tex_cotton_twill_chino/`:

| File | Bytes | SHA256 |
| --- | ---: | --- |
| candidate_4x.png | 133220196 | d2573e8a99a3bf689d74c85d9ede6840b614a78d51ea850d0efec685bcab655a |
| bicubic_4x.png | 118904114 | e3d121853a63ce85c11339444530bb920f6d100d5e993eb3f9e807c67c81af47 |

Both headers and IEND trailers were verified. This is not a full decode or a
quality verdict. Root intentionally sent SIGTERM at 20:40 elapsed (exit 143).
An ordinary Pillow header probe rejected the output size under default pixel
limits. Root mistakenly inferred that the live report would inevitably reopen
these PNGs through that reader and stopped prematurely. Source tracing corrected
this: live crops use in-memory arrays and blind publication copies files.
The probe establishes a cached-artifact/import limitation only. No OOM,
unavoidable live-report failure, acceptance score or model-quality failure is
claimed for this interrupted trial. The candidate PNG must not be substituted
for unavailable raw model output in raw-quality evaluation.

Private monitoring, log and explicit correction are in
`release-evidence/memory-audit/twill-53f1995*` under the same private root.
[Issue #135](https://github.com/TheHighBrid/Fidelis/issues/135) tracks validated
cached artifact reading and raw-generation checkpoints for honest resumption.
SwinIR production terms remain unresolved; this does not promote the model.

## Exact approved asset recovery

Shopify original-size inventory: 2313 files over 24 pages, including 2304 images.
One additional exact approved synthetic/non-GT asset, `mel096`, recovered:
`Woman_wearing_green_sunglasses_4c782fac_2K (1).jpg`, 2266578 bytes,
SHA256 `24db36517ae4580a782da8d6f60c7414426814e7c9d4689b141f9ed4fd2f748c`.
Verified copy is in the private master root. Approved exact local matches rise
from eight to nine; photographic GT coverage does not increase.

Both connected Drive image inventories were fully paginated: 46 images/one page
and 2010 images/21 pages, with no remaining page tokens. Byte-size screening
against 97 approved assets followed by candidate hashing found no additional
exact matches. A same-size mel054 candidate failed SHA verification and was
rejected. Receipts are under private `release-evidence/asset-recovery/`:
`shopify-originals-20261125.json` and `drive-full-image-pagination-20261125.json`.
Archive/source-attachment recovery remains an independent alternative.
Fixed corpus inventory remains 45/60, not 45 tested cases.

## Source-level split integrity

Frozen 60-case and approved 97-asset manifests overlap in 30 source hashes;
12 have differing split labels. Retained reports establish actual calibration
exposure for source `bd1249a6e7ea02a231d199035a578d1b391815f8e57389aec2de1c28ebacb91b`
(`mel014`, frozen `por_held_high_iso_backstage`). Three calibration diagnostics
precede two frozen-held-out diagnostics on that source. This proves exposure,
not that thresholds, weights or model selection were tuned from it. Historical
outputs and timings retain their stated diagnostic use; those comparisons cannot
claim untouched held-out evidence. Empty case-ID contamination lists do not
establish source-hash isolation. No split or criterion has been changed.
See [#134](https://github.com/TheHighBrid/Fidelis/issues/134); private ledger:
`release-evidence/split-audit/{findings.md,audition-source-ledger.json}`.

## Remaining gates and next work

Implement source-hash split preflight (#134) and raw checkpoint/resume support
(#135), then complete native evaluation with honest raw/final separation.
Continue source recovery and free compatible texture-backend qualification.
Corpus completion, comparable full-resolution evaluations, blind human reviews,
outstanding physical-device/colour checks, frozen packaging/clean install and
final creative/release approval remain open. No broad owner evidence package is
requested; no production release is authorized or declared.
