# Source-hash split preflight · issue #134 · 2026-11-25

Scope claimed from main `5099a7a`: additive source manifest audit module, CLI,
regression tests and CI entry. No image pixels, frozen labels or quality thresholds
change. Existing candidate/evidence PR #136 stays on its unchanged commit.

## Fixed acceptance criterion

Before qualification, explicitly supplied source manifests must be checked by
SHA256, not just case ID. Identical source hashes with calibration and held-out
labels must produce a nonzero exit and list every alias needed to locate the
conflict. Invalid entries/hashes must fail closed; missing hashes must be reported
as incomplete evidence, never counted as proven isolation. Same-split duplicates
may be reported without treating them as cross-split exposure. No automatic
relabel, deletion or substitution is allowed. This static inventory audit cannot
prove whether a source influenced historical tuning or certify human blindness.

## Existing evidence and remaining work

[Issue #134](https://github.com/TheHighBrid/Fidelis/issues/134) retains the actual
historical exposure audit. Manifest conflicts and missing sources remain release
gates after this tool is added; a working detector does not resolve the corpus.
Use the fixed frozen manifest together with the approved Melato inventory. Keep
the JSON report off-repo if local manifests contain private metadata. No image
or connected-service access is needed to run the manifest audit.

## Implementation and actual result

`scripts/check-source-split-isolation.py --manifest experiments/corpus_manifest.json
--manifest experiments/melato_corpus_manifest.json` emits JSON and exits 1 on
blocked/incomplete evidence (0 only when declared identities are isolated).
The module checks both cases/assets schemas, aliases by exact SHA, invalid or
disagreeing nonempty hashes, duplicate IDs, missing identities and split labels.
Unknown hashes remain incomplete rather than being grouped as one source.
It does not automatically intercept audition runs or establish historical exposure;
run it explicitly before corpus qualification. Source bytes/derivatives are outside
its declared-hash scope.

Actual manifests at base `5099a7a`: **blocked**, 112 unique declared hashes,
12 cross-split conflicts, 15 unknown hashes, zero malformed-record errors.
Private report: `~/melato-corpus/fidelis/release-evidence/split-audit/preflight-5099a7a.json`.
No manifest entry was changed. Eight preflight regressions and 35 adjacent
quality/corpus tests pass; seven release-packaging tests pass. Import sorting and
diff whitespace checks pass. Required CI includes the new regressions; packaging
requires the module, CLI and tests. This is detection, not F13 quality acceptance.
