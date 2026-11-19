# Corpus inventory checkpoint · 2026-11-10

F12-A / MEL-79, based on `c15d10d49bd3c2baae23c2bd9e27a5fa3cd3f328`.
Isolated branch: `work/mel-79-corpus-manifest`; delivery in Studio PR #12. The
commit containing this receipt is the implementation SHA. Tooling is verified,
but F12-A remains In Progress: production image/permission/coverage acceptance
is incomplete. No production corpus lock or tuning acceptance is claimed.

## Delivered

- Versioned five-category/60-slot protocol and fixed 30 calibration/30 held-out
  slot design, with hash-pinned inventory references.
- Actual inventory/fingerprint audit for eight tracked regression assets.
  Three are procedural fixtures; three have curation-script references; two older
  user-test files have unresolved source type/permission provenance. No rights,
  transcripts, critical ROIs or subject attributes were invented.
- Separate local audit/freeze/verify CLI. It rejects incomplete permissions,
  missing/changed sources/evidence, unknown or duplicate slots, cross-split groups,
  duplicate byte/decoded-pixel content, unreviewed/outside ROIs and missing text.
- Explicit coverage review gate, unsigned snapshot semantics and exclusive lock
  creation. Existing legacy synthetic-fill helpers cannot supply production cases.
- Corrected the old crop-fetch script's blanket rights wording. It was not run;
  no external images were downloaded or uploaded.

## Actual readiness

**8 regression assets available; 0 production-eligible cases; 60 slots unfilled.**
The audit succeeds as an inventory operation while reporting production_ready=false.
`--require-ready` and freeze refuse production acceptance. Design hashes pin the
proposed selection structure; they do not freeze an unavailable image selection.
Approval fields are declarations backed by local records, not legal certification.
Near duplicates and true group/coverage/source provenance still need human review.

## Verification

Full Python discovery: **114 passed**, including 12 new corpus-contract tests.
The corpus target was rerun after adding the checked-in audit snapshot assertion.
Static smoke, Python compilation, diff checks and documentation/backlog/YAML
validation passed. New tests cover fixture freeze/verify, incomplete real inventory,
missing/changed assets/evidence, rights/coverage gaps, duplicates/re-encoding,
leakage groups, ROI/text errors, root/symlink escapes and CLI no-overwrite/exit codes.
The 60-case synthetic metadata fixture exercises validation only, never quality.

No Studio UI changed, no new browser/device acceptance was performed, and no live
GPU/comparator inference or paid API call was used. Existing image-quality claims
were not renewed. Source decoding has explicit limits; target-device RSS/latency
and authoritative rights review remain unqualified.

## Next action

Populate rights-cleared production cases and critical ROIs, complete source-group
and coverage review, then create the actual lock before calibration. Independent
work can proceed on F09 confidence-gated mask interfaces and F08-B device review.
Actual comparator output and F13 parity acceptance remain blocked on the real
corpus and compatible live workers. See [corpus contract](../../BENCHMARK_CORPUS.md).
