# Explicit benchmark corpus and freeze contract

This lane prepares F12-A without pretending that the current regression crops are
a finished quality benchmark. It does not download images, upload user files,
generate missing cases or call a model. The legacy `EvaluationCorpus` discovery
and synthetic-gap helpers remain separate and cannot populate a production lock.

## Current evidence

The checked-in inventory has eight tracked regression assets: three procedural
fixtures, three crops referenced by the skimage curation script, and two older
user-test files whose source type and permission records are unresolved. The two
astronaut-derived crops share a source group. Labels describe the existing files
or generator references, not an inference about a person's identity or consent.

All eight assets have recorded file/decoded-pixel hashes, dimensions, format,
mode, ICC presence and orientation. None has been promoted into a production slot.
No independently reviewed permission/subject-consent record was located in the
repository. A filename, a previous test run or a curation script's blanket rights
claim is not permission evidence.

**Current readiness: 0 production-eligible cases, 60 unfilled slots.**
The actual production corpus is not frozen, and quality tuning/acceptance against
that corpus cannot start. [Audit snapshot](../config/benchmark/inventory-audit-v1.json).

## Versioned design

| File | Purpose |
| --- | --- |
| `config/benchmark/protocol-v1.json` | Proposed coverage, split, review and comparator protocol |
| `config/benchmark/slots-v1.json` | Exactly 60 named slots, six calibration and six held-out per category |
| `config/benchmark/inventory-v1.json` | Actual assets and explicit missing metadata; no assumed approvals |
| `fidelis/eval/corpus_manifest.py` | Canonical v1 validator, readiness report and unsigned lock logic |
| `scripts/benchmark-corpus.py` | Local audit/freeze/verify entry point |

The five categories are portrait, model-plus-apparel, textile, macro and
packshot/edge cases, 12 each. Coverage review must address skin/lighting variety,
material types (including satin/knit/twill/leather/denim), logo/zipper/engraving/seam
ROIs and background/shadow/alpha/low-light cases. Do not infer ethnicity from images.
The plan and slot assignments are pinned by hashes before tuning; that does not
mean the unavailable images have been selected or the corpus itself frozen.

Assign related subjects, products, captures and derived crops to a common opaque
`leakage_group`. A group cannot appear in both splits. Byte-identical and identical
RGBA decoded-pixel copies cannot count as separate production cases, even when
PNG encoding/metadata differs. Near duplicates, related views, misleading group
labels and source authenticity still require human review; the tool does not
recognize identities or prove that an image is a real photograph.

Changing the protocol or slot plan changes its digest and invalidates manifests
that still reference the older design. Do not tune on held-out cases or silently
reassign them after viewing results. An unsigned hash record is not access control;
protect held-out data operationally and pin the accepted lock in version control.

## Inventory record requirements

| Field | Contract |
| --- | --- |
| `id` | Unique lowercase identifier |
| `role` / `slot_id` | Regression has no slot; production occupies exactly one known slot |
| `category` | Must match the assigned production slot |
| `source_kind` | Production must explicitly declare photograph; synthetic/unknown remain ineligible |
| `source` | Root-relative path and all fingerprints returned by `inspect_image` |
| `rights` | Status, local evaluation permission, subject-consent outcome, separate remote-processing decision, basis, reviewer/date and hash-pinned local evidence |
| `leakage_group` | Explicit subject/product/capture family, not guessed from a filename |
| `target_dimensions` | Positive integer width/height for the comparator run |
| `expected_behavior` | Enhance or deliberately reject an unsupported input |
| `rois` | At least one reviewed critical rectangle `[x,y,width,height]`, kind and preserve/texture-allowed policy |
| `text_review` / `known_text` | Completed review and exact transcripts linked to every text ROI |

Source ROI coordinates are zero-based native image pixels. Negative/outside
rectangles are rejected, never clamped. ROI kinds include skin, hair, fabric,
identity, logo, text, seam, hardware, background, highlight, shadow and alpha boundary.
A source without visible text can have an empty transcript list after explicit
review. Do not invent transcripts or treat unknown text as correct.

`rights.subject_consent` must be `approved` or explicitly `not_required`, supported
by the reviewer/evidence record. `remote_processing` can be `allowed`, `denied` or
`unknown`; local readiness does not authorize cloud processing or redistribution.
Evidence can remain private beneath an explicit local root. Store internal record
references rather than personal contact details in shared metadata. Metadata
validation verifies declared records and hashes, **not legal sufficiency or truth**.

The manifest also needs an approved, hash-pinned `coverage_review` covering the
whole selection, group assignments, annotations and protocol strata. A fixture can
exercise those fields in tests, but cannot supply real production review evidence.

## Commands and exit meanings

From the repo root:

```bash
.venv/bin/python scripts/benchmark-corpus.py audit config/benchmark/inventory-v1.json
.venv/bin/python scripts/benchmark-corpus.py audit config/benchmark/inventory-v1.json --require-ready
```

Audit exits 0 for a valid inventory report even when sources or permissions are
missing. `--require-ready` exits 1 until complete; malformed schema/input exits 2.
The readiness boolean and blockers are authoritative, not a generic successful
process exit. The committed inventory intentionally cannot pass `--require-ready`.

For private production assets, create a separate manifest under an ignored local
workspace, point `--root` at the authorized image/evidence directory and retain
relative paths. Populate fingerprints using the local `inspect_image(path)` helper;
never hand-type a plausible hash or mark permissions approved from inference.
After all 60 independent cases and reviews are complete:

```bash
.venv/bin/python scripts/benchmark-corpus.py freeze .cache/benchmark/manifest.json \
  --root /absolute/path/to/authorized-assets \
  --output .cache/benchmark/corpus-v1.lock.json
.venv/bin/python scripts/benchmark-corpus.py verify .cache/benchmark/corpus-v1.lock.json \
  --root /absolute/path/to/authorized-assets
```

The output directory must already exist. Freeze creates a new file exclusively
with private file permissions; it never overwrites a source, prior lock or other
file. A lock snapshots the manifest/design, hashes and split, not copies of images.
Verify rechecks source/evidence bytes and readiness. Missing/changed data invalidates
it. The record is explicitly unsigned; its digest is reproducibility evidence,
not a signature or defense against someone rewriting both content and hashes.

Single-frame sources are limited to 200 MiB and 40 MP. Sources are fully decoded
for validation; pixel hashing uses bounded RGBA row conversions. There is no M1/8K
RSS or latency certification. Absolute paths, parent escapes and symlinks outside
the explicit asset root are refused. Nothing is fetched from the network.

## What remains

Source and annotate the actual consented/licensed corpus, finish permission and
coverage reviews, then create the real lock before tuning. Prepare dated Clarity/
Krea and other comparator outputs with exact settings/cost/time/output hashes only
when access and processing permission exist. Each output stays a separate full-size
file. Missing competitors and unavailable model runs remain missing evidence.
F12/F13 and commercial parity remain open.
