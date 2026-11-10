# Fidelis Studio: quality and execution plan

Version: 1.0 | 2026-11-10 | Status: implementation started, competitive parity unproven.

## 1. Product commitment

Build a focused restoration studio for Melato editorial, apparel, hardware macro,
and ecommerce photography. Benchmark Clarity's controlled generative enhancement
and the requested Krea-style regional editing experience. Ship independent
full-resolution images, never collages or contact sheets.

The goal is believable photographic detail with control over where reconstruction
is allowed. Reconstructed detail is plausible synthesis, not recovered evidence.
The app must preserve identity, garment construction, typography, dye colour,
lighting, depth of field, and background restraint before maximizing sharpness.
Do not claim market leadership or parity until the blind benchmark passes.

Scope: local single-user studio, single images and folder batches, native ARM64
precision lane, optional explicitly selected GPU generation, editable region masks,
repeatable exports, and cost/evidence tracking. Exclude video, audio, stock assets,
public multi-tenant billing, foundational model training, and new orchestration
infrastructure without a measured need.

## 2. Repository baseline and continuity

Audited main at `0f10ca6`. Reuse `bin/fidelis`, candidate registration and checksums,
`fidelis/engine/tiler.py`, disk-backed `streaming.py`, the existing web UI,
colour correction, evaluation corpus, and audition scripts. Do not replace these
with the pasted standalone FastAPI prototype. First build the compositor as a
testable library and CLI; integrate it through the existing UI next. Introduce an
API framework only when durable job handling requires it and migration is tested.

The README records that Nomos produced synthetic/checkerboard texture and that a
previous source-fusion stage softened useful VOSR detail. Preserve VOSR as a
quality challenger; do not reinstall Nomos as the untested default or impose global
source blending. Any new colour/detail fusion must beat those rejected behaviours.
Existing diffusion schedule classes configure parameters; they do not constitute
a working diffusion inference backend. Installed, runnable capabilities must be
distinguished from named candidates throughout the product.

## 3. Corrections to the pre-plan

| Assumption | Engineering decision |
| --- | --- |
| Deterministic SR guarantees original geometry | It is repeatable, not lossless. GANs can invent weave and text. Compare multiple bases and include a clearly labelled interpolation baseline. |
| 85-95% generated skin is universally realistic | Treat weights as calibration candidates. Preserve eyes, teeth, moles, facial landmarks, and depth of field; split hair from skin. |
| Sobel identifies stitching and hardware | It identifies contrast, including pores and weave, and misses low-contrast hardware. Use it as a secondary heuristic, never semantic proof. |
| BiRefNet provides internal material classes | Foreground matting supplies silhouette alpha, not logos, seams, skin, or material labels. |
| ATR parsing distinguishes all fabric and hardware | Its labels do not include zipper teeth, logos, stitching, or leather grain. Add explicit protected masks and uncertainty. |
| No person detected means all foreground is fabric | Unsafe. Unknown product regions remain protected until classified or painted. |
| Resize cloud result to align it | Equal dimensions do not imply alignment. Reject mismatches, validate crop/padding transforms, and detect internal geometric drift. |
| Flux is an SDXL graph with three edited nodes | Use a separately exported and tested model-family graph with compatible encoders, VAE, conditioning, guidance and ControlNet. |
| Arbitrary Lightning weights accept ordinary SDXL schedules | Pin exact weights and their documented sampling recipe; benchmark separately. |
| Creativity/fractality sliders map universally | Provider adapters own units and bounds. Clarity's repository and hosted endpoints may differ. No invented slider equivalence. |
| Grain repairs plastic skin | Grain can hide a defect without restoring detail. Off by default, optional finishing only after benchmark evidence. |
| LAB channel replacement guarantees dye fidelity | Gamut, luminance, ICC and quantization still matter. Measure colour drift; do colour work before a final exact protected-pixel restore. |
| uint8 arrays produce true 16-bit detail | uint16 containers do not create precision. Maintain a float working path and document source/model precision. |
| 4x always means 8K | Output is source width and height multiplied by scale. Display exact dimensions and megapixels. |
| Local/8K processing takes fixed milliseconds | Benchmark by device, source dimensions, tile size, cold/warm state and precision. Never publish unmeasured speed guarantees. |
| Five cached jobs fit any machine | Use byte budgets, disk-backed intermediates, retention and bounded concurrent inference. |
| Local failure should silently send to cloud | Keep execution local unless the user selects a cloud policy. Persist provider request IDs before retrying. |
| C2PA-looking JSON is verified provenance | Unsigned sidecars are execution records, not verified C2PA signatures. Audit existing provenance claims before release. |

## 4. Target processing architecture

1. **Ingest and preflight.** Validate decoded bytes, pixel count and supported bit
   depth; normalize EXIF orientation; preserve alpha separately; read/convert ICC
   explicitly. Derive exact target dimensions and resource/cost estimate. Hash
   source, configuration, model weights, workflow and masks.
2. **Precision base.** Select an installed benchmarked model through the existing
   registry. Tile within a measured memory budget and stream the output to disk.
   Missing weights are an actionable error, not a silent Lanczos substitution.
   Interpolation is a legitimate, explicitly selected benchmark/fallback mode.
3. **Region preparation.** Parse at a bounded working resolution. Aggregate class
   probabilities before full-resolution refinement to avoid an 18-channel 8K
   tensor. Refine with overlap and inspect collars, cuffs, hair and transparent
   edges. Store separate skin, hair, fabric, protected, background and confidence
   maps. Unknown pixels default to base. Explicit protection wins every overlap.
4. **Texture candidate.** Run one pinned, validated backend first, initially SDXL
   or a schema-verified Clarity API. Condition on the exact base with documented
   transforms. Treat FLUX, SUPIR and VOSR as separate adapters/challengers.
   Masked generation is preferable when validated; unmasked generation followed
   by compositing is a baseline and can still affect neighboring receptive fields.
5. **Candidate validation.** Reject invalid shapes, NaNs, corrupted output, and
   unaccounted orientation/crop changes. Compare identity, OCR and geometric drift.
   Protect or reject defective regions rather than resizing errors away.
6. **Composition.** Blend in linear-light float working space. Texture alpha is
   normalized semantic weights multiplied by confidence and optional edge restraint.
   Apply user protection last with exact base copy for fully locked pixels. No
   whole-frame finishing after hard protection unless it reapplies that guarantee.
   A frequency-limited detail residual is a benchmarked alternative, not a default.
7. **Review and export.** Preview at bounded resolution, inspect native 100/200%
   crops, then perform a full-resolution render on commit/export. Reblend does not
   rerun diffusion. Preserve colour/alpha intentionally, write atomically, verify
   the encoded artifact, and retain a reproducibility sidecar.

Core contracts: `ImageArtifact` (dimensions, dtype/range, colour space, orientation,
alpha, checksum, path), `RegionMasks` (float [0,1], same grid, explicit semantics),
`GenerationRecipe` (backend family/version, seed, all resolved parameters),
`BackendCapability` (available versus tested, native scale, max pixels, precision),
`JobManifest` (stage/status, hashes, request IDs, costs, errors, timestamps).
Never accept positional node-number deletion as workflow construction. Build a
base-only graph from its actual ancestors and validate against `/object_info`.

## 5. Four profiles and controls

| Profile | Default policy | Must preserve | Experimental tuning |
| --- | --- | --- | --- |
| Packshot Strict | Precision only; no generated pass or semantic models | Type, hardware, silhouette, shadows, background | Base model selection only |
| Luxury Apparel | Low generated blend, confidence gated | Logos, stitching, zip, garment fit, skin identity | Separate skin/hair/fabric controls |
| Editorial Skin | Conservative skin, independent hair | Identity, features, age, marks, skin tone, bokeh | Local denoise/strength sweeps per backend |
| Macro Product | Precision default; material enhancement opt-in | Engraving, stitch count, bevel, highlights | User-selected material interior only |

Start with conservative blend candidates (skin .25, hair .20, fabric .15); they are
not quality-certified presets. Unknown/background/hardware alpha is zero. Keep
advanced denoise, tile context and resemblance under backend-specific controls.
Do not name nonexistent LoRAs in production config. Each model requires an actual
download source, revision, hash, architecture and license record.

Studio design: premium near-black workspace, restrained cream accents, large image
canvas, compact controls and readable status. Primary path: open, choose profile,
review masks/cost, enhance preview, refine, export. Provide true mask painting with
protect/skin/hair/fabric tools, brush size/hardness/opacity, erase, undo/redo,
zoom/pan, keyboard and touch support. Overlays are diagnostics; they do not replace
editable masks. Compare original, precision base, raw generated candidate and final
on the same grid. Switching a generation recipe marks the candidate stale; changing
only blend weights may reuse it. Never label a reblend as a new model inference.

## 6. Jobs, performance, security and packaging

Use a single-user SQLite job ledger and bounded worker queue, not synchronous
long-running upload requests or unbounded FastAPI background work. States:
queued, running(stage), awaiting_review, completed, failed, cancelled. Persist stage
artifacts; recover unfinished work after restart. Serialize GPU model loading and
inference. Support cancellation, deadline, atomic outputs and graceful shutdown.

Comfy client: open websocket before submission, correlate every event by prompt
ID, handle execution_error/interrupted/cache-hit events, add deadline and polling
reconciliation, isolate per-job upload names and retain subfolder/type metadata.
Cloud client: schema snapshots, supported scale checks, capability probes, download
size/time limits, validated output shape/transform, request ID persistence, cost
reservation and reconciliation. An ambiguous timeout must not trigger a second
billable submission or cross-provider failover. Keep keys out of browser/logs.

Default bind is loopback. Validate uploads by decode rather than extension, limit
bytes and pixels, constrain artifact paths, reject untrusted arbitrary download
URLs, and avoid static directory exposure. Cloud upload/retention policy must be
visible. No automatic remote-code model loading from an unpinned revision.

Performance targets to validate: <=200ms p95 reblend at <=1MP preview, <=100ms input
feedback independent of worker, bounded memory under a configured device budget.
Full 4K/8K export is asynchronous and separately measured. On an 8GB M1, keep one
heavy model resident at most; generative CUDA workers are optional. NCNN/Vulkan
remains the native Android precision route. MPS and ONNX/CoreML are separate tested
capabilities, never assumed interchangeable.

## 7. Benchmark and release gate

Freeze a consented/licensed 60-image corpus: 12 portraits across skin tones,
12 model-plus-apparel frames, 12 textiles (satin, knit, twill, leather, denim),
12 macros (zipper, logo, engraving, seam), and 12 packshots/background/alpha/low-light
edge cases. Split 30 calibration / 30 held-out before tuning. Retain current real
crops and synthetic fixtures as regression tests, not substitutes for this corpus.

For each image store input hash, permissions, category, target size, critical ROI
masks and known text. Run interpolation, best installed deterministic model,
current Fidelis, VOSR challenger, pinned Clarity, and dated Krea settings where
accounts permit. Same source, target dimensions, export quality and disclosure of
manual adjustments; record actual cost and elapsed time. No commercial accounts or
paid inference are required for unit tests. Missing comparator outputs are reported
as missing evidence, never fabricated scores.

Quality gate order:

1. Hard integrity: exact dimensions, no invalid pixels, correct orientation/alpha,
   verified exports; zero changes to fully protected base pixels in compositor tests.
2. Source fidelity: zero confirmed altered logos/text, zipper/stitch construction,
   identity changes, or invented product features in held-out review. OCR and
   landmarks are screening tools, not guarantees. Legitimate black backgrounds
   must not be labelled failed black tiles merely because they are black.
3. Appearance: blind pairwise review at fit, 100% and 200% with randomized labels.
   Score skin realism, fabric coherence, edge quality, colour/light preservation,
   background restraint and overall publishability. Automated/LLM judges assist;
   they do not replace visual acceptance. Never call a high-frequency proxy LPIPS.
4. Parity proposal: held-out preference plus ties >=80% against each target and
   wins >=50%, no category below 60% preference plus ties, no critical defects.
   Report sample count and bootstrap confidence intervals; with only 30 held-out
   images evidence is preliminary. Expand to >=100 held-out before broad leadership
   claims. PSNR/SSIM apply to paired ground-truth restoration cases; not a sole gate
   for synthesized detail. Report true LPIPS only with its implementation/version.
5. Operational gate: restart/cancel/disk-full/provider-error tests, deterministic
   compositor regressions, Linux/macOS CI, measured M1 memory, native Android
   precision smoke and successful export round trips. No unmeasured latency claims.

## 8. Costs and license checkpoints

Fal's model page currently lists $0.03/MP. Illustrative arithmetic, USD assumed and
to be confirmed against billing: 3840x2160 = 8.2944MP = $0.248832; 7680x4320 =
33.1776MP = $0.995328. One hundred outputs are roughly $24.88 or $99.53 respectively,
before pricing granularity, repeated previews or other billable processing.
The original $1.50-$3.00/month claim is not an accepted budget. Provider rounding,
scale=1 acceptance and actual billed units must be verified. Store rate date,
currency, reservation and actual cost. Local has zero API fee, not zero electricity,
hardware cost or latency. Self-hosted cost includes warm-up, idle time, storage,
upload and failed compute. Set per-job/monthly caps before enabling paid execution.

Record licenses independently for code, checkpoint, LoRA, ControlNet, segmentation
weights and training data restrictions. Clarity source is AGPL-3.0; do not copy its
implementation into this MIT repo without resolving obligations. Its current Flux
implementation is described upstream as not open source. FLUX.1-dev has specific
non-commercial model-use terms and separately discusses outputs; do not infer
unrestricted commercial model deployment from commercial output permissions.
SegFormer clothes is marked `license: other`; clear production suitability before
shipping weights. Prototype with manual masks while this is unresolved.

## 9. Ordered execution backlog

Each task finishes with code, tests, evidence, and an updated task status. Estimates
are focused developer days, exclude GPU procurement and external review, and are
planning ranges rather than delivery promises. Rough solo scope: 9-14 weeks plus
model/licensing uncertainty. Cut optional adapters before cutting quality gates.

| ID | Task and deliverable | Depends | Estimate | Acceptance |
| --- | --- | --- | --- | --- |
| F01 | Audit baseline, correct assumptions, publish this plan | none | 1 | Existing quality decisions retained; sources attached |
| F02 | Validated region compositor and conservative profiles | F01 | 2-3 | Locks, uncertainty, shape/range, linear-light tests |
| F03 | File CLI for aligned passes, masks and evidence sidecar | F02 | 1 | Actual image export and reblend without inference |
| F04 | Freeze artifact/mask/recipe contracts and byte-budget storage | F03 | 2-3 | Restart reload, schema migration, budget enforcement |
| F05 | Capability/weight registry, measured base-model audition | F04 | 3-4 | Missing models fail clearly; selected base has evidence |
| F06 | One pinned SDXL/Clarity backend, base-only fast path | F05 | 4-6 | Live GPU output, object_info/schema validation, exact size |
| F07 | Durable queue, cancellation and provider reconciliation | F06 | 3-5 | Timeout cannot double-submit; restart/cancel tests |
| F08 | Manual region editor and revisioned preview/reblend UI | F03,F04 | 4-6 | Touch/keyboard, undo, stale-response handling, native zoom |
| F09 | Segmentation candidate/license audition and confidence masks | F05,F08 | 4-6 | Boundary annotations, unknown protected, low-RAM inference |
| F10 | Logo/seam/hardware protection and drift screening | F06,F09 | 4-6 | Critical ROI benchmark, explicit overrides win |
| F11 | Colour/alpha/precision export, no default grain | F10 | 3-4 | ICC/alpha/16-bit round trips, locked pixels retained |
| F12 | Freeze 60 cases, reproducible comparator runners/report | F05 | 3-5 | Split, hashes, independent full-size outputs, honest metrics |
| F13 | Tune on calibration set, blind held-out acceptance | F06-F12 | 5-8 | Quality gates above; failures create defects, not claims |
| F14 | Batch recipes, bounded scheduling and disk/memory budgets | F07,F11 | 3-4 | Interrupted batch resumes without duplicate paid jobs |
| F15 | Premium responsive UI polish, accessibility and packaging | F08,F14 | 4-6 | Real-device checks, install/upgrade/rollback paths |
| F16 | Release candidate, documentation, limits and evidence | F13,F15 | 2-3 | CI green, no critical defects, measured parity report |
| F17 | Optional FLUX/SUPIR/self-hosted challenger adapter | F16 | 5+ each | Only promote on quality/cost win with cleared licenses |

Milestones: M0 F01-F03 foundation; M1 F04-F07 runnable two-pass alpha;
M2 F08-F11 editable protected restoration; M3 F12-F13 measured quality beta;
M4 F14-F16 daily production release. Do not mark M1 complete from mocked providers.

## 10. Immediate execution and evidence policy

Start F02/F03 now with supplied aligned passes and explicit masks, without model
downloads, paid calls, invented segmentation or replacing working CLI behaviour.
This provides a real, testable compositing capability while separating model quality
experiments from application correctness. Next implement F04 and wire F08 preview
editing, then promote one backend only after its integration test passes.
Track current results in `docs/FIDELIS_STUDIO_TASKS.md`. Failed experiments retain
their settings and reason; never repeatedly ask the owner to retest a known failure.

## Primary references checked 2026-11-10

- https://github.com/philz1337x/clarity-upscaler (architecture, license, Flux distinction)
- https://github.com/philz1337x/clarity-upscaler/blob/main/predict.py (provider-independent upstream input definitions)
- https://fal.ai/models/fal-ai/clarity-upscaler/api (current hosted schema)
- https://fal.ai/models/fal-ai/clarity-upscaler (displayed $0.03/MP rate)
- https://fal.ai/docs/documentation/model-apis/pricing (billing units and dynamic rates)
- https://huggingface.co/mattmdjaga/segformer_b2_clothes (ATR labels, evaluation, license metadata)
- https://docs.comfy.org/tutorials/flux/flux-1-text-to-image (Flux loading and conditioning)
- https://huggingface.co/black-forest-labs/FLUX.1-dev/blob/main/LICENSE.md (model versus output permissions)
- https://www.krea.ai/apps/enhance (product benchmark; detailed region-mask parity requires hands-on evidence)

Provider pages can change. Freeze actual schemas, revisions, prices and license
text at implementation time. The requested region workflow is a product requirement;
this audit does not claim a verified inventory of Krea's current mask controls.
