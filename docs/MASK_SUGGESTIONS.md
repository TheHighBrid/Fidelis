# Source-bound mask suggestions

This F09 interface accepts **imported class probabilities** and proposes editable
masks. It does not ship, download or run a segmentation model. Automatic candidate
selection, actual label/terms qualification and real collar/cuff/hair/product
accuracy remain open. There is no skin-colour heuristic or guessed hardware class.

## Review in the editor

Open a saved regional job. In **Mask suggestions · advanced import**, select an NPZ
probability archive and matching JSON receipt, then stage it. Save or discard
unsaved edits first; the editor refuses to silently reset them.

Staging persists a proposal and advances the saved revision without changing the
master, active masks or blend weights. Toggle **Preview staged proposal** to inspect
a separate coloured overlay. It is a proposal, not the active mask or a realistic
image-quality preview. Its accepted fraction refers to the low-resolution score
grid and is not an accuracy statistic or a measure of native-image coverage.

**Accept into empty regions** commits a new mask/blend revision. It fills only
pixels where all saved semantic masks, confidence, protection and edge guard are
zero. Existing paint, confidence-only erasures, fractional protection and hard
locks remain unchanged. Proposed protected classes can lock previously untouched
pixels. Unknown/unaccepted probabilities contribute no generated alpha; they do
not become permanent protection locks, so the user can paint them later.

Accepted masks can be edited with the existing brush tools. There is no saved-
revision undo added here. Discard an unaccepted proposal to remove it without
changing the master. A later edit/generation makes acceptance stale; discard or
stage again instead of merging against unseen changes. Packshot Strict rejects
suggestions. Staging can make an in-flight generation's source revision stale;
that generation's result then fails the existing revision check.

## Probability and receipt contract

NPZ must contain exactly one NPY v1 C-contiguous float32 array named
`probabilities`, shaped `[classes, score_height, score_width]`. There must be 2..32
classes, sides up to 1024 and at most 64 MiB expanded/compressed probability data.
Every value is finite and in [0,1]; the complete class distribution sums to one
per pixel within 0.001 floating-point tolerance. Logits, partial class selections,
object arrays, duplicate/unexpected archive members and invalid shapes are refused.
The browser import cap is 24 MiB combined files; the existing JSON request cap is
48 MiB. A receipt is bounded to 64 KiB.

The JSON receipt has these required fields:

| Field | Meaning |
| --- | --- |
| `schema_version` | Integer 1 |
| `base_artifact_sha256` | Exact saved base NPY artifact hash from the job; not the uploaded PNG file hash |
| `input_dimensions` | Original `[width,height]` matching that base |
| `transform` | `full_frame_resize_no_crop_no_rotation` only |
| `model` | Actual `id`, `revision`, `weights_sha256` and `terms_reference` declarations |
| `labels` | One object per actual output channel, with unique `name` and explicit `region` |

Allowed routing regions: unknown, skin, hair, fabric and protected. Supply the
model's actual channel ordering and labels. Multiple channels can map to one
region; omitted label channels or inferred IDs are forbidden. Map unsupported
classes to unknown. Declared hashes/references identify the claimed origin;
the importer does not independently inspect remote weight bytes, licenses or label
truth. Saved metadata explicitly records qualification as false. Never put private
credentials in a receipt.

The score grid must cover the entire orientation-normalized source frame. There
is no crop/padding/rotation/affine correction. A falsely declared transform or
confident misclassification cannot be detected by dimensions/hash checks alone.
Those require actual model validation and visual ROI review.

## Conservative routing

Class probabilities are summed by routing region. A winner is accepted only when
it is a non-unknown region, its score meets the threshold (default 0.90), and its
lead over the runner-up meets the margin (default 0.15). By default permission is
eroded by one score-grid pixel around uncertainty, class boundaries and frame
edges. Confidence remains the accepted region score, not a calibrated probability
that the mask is correct. Floating-point overshoot in aggregated confidence is
clipped to the mask domain; partial input distributions are not renormalized.

Masks expand to native dimensions with explicitly recorded whole-frame nearest
mapping. This is not high-resolution matting, guided boundary refinement, seam
recognition or zipper/logo detection. Fine flyaway hair and narrow stitching need
model-specific validation and later refinement. Conservative settings are initial
heuristics, not universal safety or realism guarantees.

## Local API and CLI

The public job manifest now includes its `base_artifact_sha256`. All endpoints
retain localhost Host/Origin/client restrictions and expected-revision checks.

| Operation | Route after `/api/regions/jobs/{id}` |
| --- | --- |
| Stage | POST `/mask-suggestions`: base64 `scores`, JSON `receipt`, integer `expected_revision`; optional threshold/margin/boundary |
| Preview | GET `/suggestion-preview?revision=N`: separate RGBA proposal PNG |
| Accept | POST `/accept-suggestion`: `expected_revision` |
| Discard | POST `/discard-suggestion`: `expected_revision` |

Staging returns 201; accept/discard return 200; stale revisions return 409; bad
scores/receipts return 400; budget failure returns 413. Threshold is constrained to
0.5..1, margin to 0..1 and boundary to integer 0..8; exposed controls do not imply
qualification of any setting.

```bash
.venv/bin/python scripts/mask-suggestion.py describe --workspace WORKSPACE --job JOB_ID
.venv/bin/python scripts/mask-suggestion.py stage --workspace WORKSPACE --job JOB_ID \
  --expected-revision 1 --probabilities scores.npz --receipt source-model-receipt.json
.venv/bin/python scripts/mask-suggestion.py accept --workspace WORKSPACE --job JOB_ID \
  --expected-revision 2
```

Use the actual revision returned by each operation. `discard` is a separate
alternative to `accept`. The describe command supplies actual source binding;
none of these commands generates probabilities or substitutes a missing model.

## Persistence and resource limits

One pending proposal is stored as five additional float32 native mask artifacts
under the existing JobStore manifest and byte budget. Its optional
`mask_suggestion` record stores recipe/receipt/score hashes and review state.
Stage/accept/discard are revision commits. Cleanup/restart/deletion include the
proposal artifacts; rollback preserves the previous manifest and master. A corrupt
proposal can be discarded, while acceptance fails its checksum check.

Native mask writes/merges are striped, but input probabilities and low-resolution
routing arrays remain in memory. Artifact staging, old masks, new masks and master
can coexist; insufficient storage headroom fails explicitly. The stripe allowance
is not total-process RSS. No 8GB M1/8K memory or latency certification is claimed.

## Evidence and remaining qualification

Synthetic probability tests cover unknown/ambiguous scores, label grouping,
boundaries, source/grid rejection, protected/manual regions, staged master
identity, restart, stale edits, rollback/budget/corruption, archive contracts and
actual local HTTP/CLI flow. Editor DOM contracts cover unsaved-edit refusal,
preview toggling and stale accept controls. These do not establish real model
inference, hair/collar boundary accuracy, rendered browser/touch acceptance or
photographic enhancement quality. F09 stays In Progress until actual model
weights/terms/labels and annotated production cases are qualified.
