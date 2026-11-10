# Risk, blocker and defect register

Snapshot: source audit of `5f32fba`, 2026-11-10. This document records known work;
the original findings remain the historical baseline, not a claim that every path was exercised.
The four D-items are actionable source-confirmed findings with direct evidence in
`backlog.json` and their Linear issue bodies. Their release blockers are linked.

## Confirmed inherited source findings

| Issue | Finding / impact | Resolution acceptance | Suggested responsibility |
| --- | --- | --- | --- |
| [D01 / MEL-73](https://linear.app/melato/issue/MEL-73/d01-correct-unsigned-provenance-reported-as-verified) | Legacy generate_c2pa_provenance emits signature_info.status=verified while creating an unsigned JSON sidecar. This was source-confirmed; no cryptographic verification was demonstrated. | Represent unsigned execution records honestly; verified/signed status requires real signing and verification evidence; regression tests cover the unsigned case. | Release / provenance |
| [D02 / MEL-72](https://linear.app/melato/issue/MEL-72/d02-remove-or-repair-invalid-large-input-pipeline-import) | The use_tiling branch imports scripts.tiled_upscale, but the tracked script is named tiled-upscale.py and no scripts/tiled_upscale.py module is tracked. This is a source-confirmed import defect; no live-model reproduction was performed in this audit. | A large-input pipeline test with a controlled runtime exercises the path without ImportError and preserves actual subprocess/output validation. | Core pipeline |
| [D03 / MEL-71](https://linear.app/melato/issue/MEL-71/d03-make-local-binding-and-deployment-policy-consistent) | The server default is 0.0.0.0 while the intended operating policy is local-only. Regional routes restrict clients; the inherited other routes are not an authenticated public service. Explicit loopback launch currently mitigates exposure. | Default launch binds loopback unless deliberately configured otherwise; tests/docs/container boundaries are consistent; no public deployment claim without reviewed authentication/storage design. | Local HTTP / packaging |
| [D04 / MEL-74](https://linear.app/melato/issue/MEL-74/d04-correct-metric-placeholders-and-pseudo-lpips-labels) | Legacy pipeline initializes numeric quality defaults and derives a value named lpips from gradient coherence. BenchmarkSuite also passes BGR arrays into functions expecting RGB in some pipeline calls. These are source findings, not trustworthy perceptual benchmark results. | Unavailable metrics remain explicitly missing; gradient proxies are labelled as proxies; colour ordering/reference semantics are correct; any real LPIPS uses its actual implementation/version; regression evidence covers failure/missing-reference paths. | Evaluation / telemetry |

The metric finding includes gradient-derived pseudo-LPIPS, numeric fallback
quality defaults, and RGB/BGR/reference semantics requiring correction. These
must not become published quality evidence. The import finding is established by
the tracked module/file mismatch; a controlled-runtime regression now exercises the actual subprocess path.

## Capability and acceptance blockers

| ID | Constraint | Evidence and impact | Next action |
| --- | --- | --- | --- |
| B01 | No configured live worker/weights in audited executor | Doctor found no native candidate/runtime or reachable ComfyUI; no live quality result exists | F05-A/F05-B prepare actual worker and provenance, then F06 live audition |
| B02 | Browser/device acceptance outstanding | Prior review browser could not connect to the execution server; Node/HTTP tests do not verify UI appearance/touch | F08-B use a reachable same-host browser/device path |
| B03 | Native inspector awaits browser/device acceptance | F08-A exact crop/paired-load implementation is protocol/DOM tested in PR #12; overview zoom remains preview-only | F08-B verify actual rendering/touch on target devices |
| B04 | No frozen production comparison corpus | F12-A tooling/inventory verified: eight regression assets, zero eligible production cases, 60 missing slots | Populate reviewed rights/ROIs/groups and freeze actual cases before F13 tuning |

## Architectural and release risks

- The chosen precision base can itself invent detail. Exact protection only
  preserves that base, not a hypothetical perfect original.
- F09 imported probability gating/review is fixture-tested; no actual automatic
  model is configured. Declared scores can be confidently wrong and nearest expansion
  is not fine matting. Segmentation labels do not inherently identify seams, logos or zipper teeth.
  Automatic masking remains a candidate, not a guaranteed structural guard.
- F11 colour-managed, straight-alpha and 8/16-bit precision export
  (`fidelis/postprocess/managed_export.py`) is verified on synthetic PNG/TIFF
  fixtures and synthetic RGB Matrix-TRC profiles only. Non-matrix LUT ICC
  conversions in 16-bit mode fail closed unless explicitly downgraded via
  `allow_8bit_lut=True`, Studio `/regions` HTTP upload/store paths remain 8-bit
  untagged sRGB PNG until integrated, and live `F06` outputs plus real
  display/print visual review remain open.
- Current inputs are untagged uint8 sRGB RGB PNGs. ICC/alpha/high-precision support
  is not established by the uint16 file container or old colour-fix claims.
- Stripe allocation limits are not total-RSS measurements. Import decoding and
  codecs still require memory, especially on 8GB Apple Silicon.
- Existing Docker/server packaging is not an authenticated public service. Regional
  loopback checks do not certify inherited routes or a production deployment.
- F07-A adds a fixture-tested bounded worker and scoped local cancellation, pending
  review/merge. Submitted GPU work can continue after local cancellation. Crash during
  apply needs ledger/job inspection; cache quotas and live/device acceptance remain open.
  No automatic ambiguous retry is allowed.
- Graph hashes do not verify actual worker checkpoint bytes or compatible terms.
  Model licences, node/runtime revisions and weight integrity require separate evidence.
- Old README/changelog promotion, speed and quality statements are historical;
  current acceptance must trace to actual images, devices, recipes and a code SHA.

## Reporting and closure

Use the defect template with exact source/runtime evidence, scope and acceptance.
Do not call a source finding a measured exploit or a model-quality result. Record
false alarms and rejected hypotheses as such. An issue closes only with its
regression/evidence receipt, delivery SHA and any remaining limitation.

## D01-D04 resolution checkpoint

All four findings have implementations and regression evidence in the Studio
branch, pending review/merge in PR #12. They remain inherited defects on the audited
main runtime until delivery merges. See the [integrity receipt](checkpoints/2026-11-10-pipeline-integrity.md).
The full Python suite passed 77 tests. Null metric compatibility, physical Delta E
recalibration and the local container/client boundary are explicit in that receipt.
No real inference, public service deployment or competitive quality was certified.
