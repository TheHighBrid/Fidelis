# Mask suggestion interface checkpoint · 2026-11-10

F09 / MEL-62, based on `10a30950c93783729d0c051fa84e7effd74011dc`.
Isolated branch: `work/mel-62-mask-suggestions`; delivery in Studio PR #12. The
commit containing this receipt identifies the implementation. F09 remains In
Progress: imported probability/review plumbing is verified, automatic segmentation
model qualification is not complete. No weights were installed or executed.

## Delivered behaviour

Added a source-bound complete class-probability contract with explicit actual label
mapping and model declarations. Conservative region mass, threshold/margin and
boundary erosion route unknown/ambiguous regions to zero permission. Expansion is
explicit whole-frame nearest mapping, not fine matting or geometry verification.

Added persisted staged proposals, a separate preview, explicit accept/discard and
CLI inspection/staging. Staging leaves the master/active masks unchanged. Acceptance
fills only untouched pixels, preserving manual semantics, confidence-only erasures,
edge guards and protection. Later edits make acceptance stale. All operations use
revision/budget/checksum/rollback contracts; corrupt proposals remain discardable.

## Verification

**125 Python tests passed**, including 11 new synthetic suggestion cases. Existing
HTTP web UI/static smoke, JavaScript syntax, Python compilation and diff checks
passed. The existing inline-editor DOM fixture now checks unsaved-edit refusal,
proposal preview and stale-accept controls. Documentation links, task mappings,
dependency DAG and YAML validated. New tests cover routing/labels/boundaries,
source/grid affinity, manual/protected pixels, stage identity/restart, stale edit,
budget/render rollback, corruption, NPZ contracts and real HTTP/CLI operations.

No actual segmentation inference, independent model terms/label verification,
collar/cuff/hair/product accuracy review, target-device memory/latency, rendered
browser/touch or live photo quality acceptance was performed. Model identity and
terms references are declarations, with qualification explicitly false. Test
probabilities are fixtures; there is no guessed checkpoint or automatic fallback.

## Next action

Qualify one actual model's weight bytes, terms, preprocessing/channel labels and
output registration. Evaluate annotated collar/cuff/hair/product ROIs and native
resource use before connecting a one-click model runner. F08-B and the real F12
corpus remain open. See [suggestion contract](../../MASK_SUGGESTIONS.md).
