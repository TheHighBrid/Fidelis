# Independent v1 evidence recovery

Candidate: main `d6f420ccf1754c79931c9822ec5127b98ab0df5c`.
Acceptance criteria remain those in QUALITY_GATES.md and the frozen protocol.

## Local worker and actual inference

Official ComfyUI `1f13e29b267f051b84e5c5476ee7a65badb28288` runs on Apple M1
with Torch 2.15.0 and available MPS. The existing preflight reports
`qualified_preflight`, `schema_compatible: true` for an explicit upscale graph.
Official Real-ESRGAN v0.2.5.0 `realesr-general-x4v3.pth` is 4,885,111 bytes,
SHA256 `8dc7edb9ac80ccdc30c3a5dca6616509367f05fbc184ad95b731f05bece96292`.
Upstream [BSD-3-Clause license](https://github.com/xinntao/Real-ESRGAN/blob/master/LICENSE).

MPS smoke input is a 59×128 derivative of the approved IMG_0932 photograph;
the original is 1170×2532. Output is 236×512; wall time including polling is
3.06965 seconds. This measurement applies only to that small smoke input.
Output SHA256: `7df4a6ce457a23a2e04ef7ea15cfd4136d24fa737460113ad7113c59fc312e07`.
Canonical workflow SHA256:
`43d8e172d4866accd97e1939c1114d7fca318a33cfe48e2ed3df9efd6a71c356`.

Private local artifacts:
`/Users/tyf12/melato-corpus/fidelis/release-evidence/d6f420cc/comfy-mps/`
contains `fidelis-workflow.json`, `fidelis-preflight.json`,
`fidelis-live-smoke-result.json`, source derivative and separate PNG output.
This establishes real local upscale execution, not SDXL qualification, final
texture quality, full-resolution resource acceptance or human review.

## Corpus and review

The 97 masters already carry owner approval (CORPUS_ACQUISITION_PROPOSAL.md).
Initial local inventory: 34 unique files, eight exact inventory SHA matches,
two exact frozen-case matches. Connected Drive recovery is possible and ongoing.
Missing category slots: portraits 2, apparel 4, textiles 10, macros 10, packshot 4.
Poly Haven's [official CC0 license](https://polyhaven.com/license) provides a
compatible source to investigate for photographic textile references. Material,
source-photo and ROI suitability must be verified individually before slotting;
rendered PBR previews must not be presented as photographic restoration truth.

Full-resolution NCNN versus bicubic audition on IMG_0932 is running, with separate
output files under `release-evidence/d6f420cc/IMG_0932/cases/melato-case/`.
Its final metrics and randomized ballots remain pending. No human score is supplied.

## Signoff and packaging

Current policy permits the same named owner in creative and release roles;
both explicit approvals remain pending. Independent F13 reviewers remain required.
The old candidate SHA is an ancestor of main; manifest merged_to_main is corrected.
Historical package digests do not verify current-candidate packages; rebuild remains
an independent engineering task. The local readiness audit verified zero packages
because historical archives are absent in this checkout.
