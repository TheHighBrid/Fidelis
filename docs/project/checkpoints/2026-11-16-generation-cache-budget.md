# F07-B: bounded local generation PNG cache

- Task: [MEL-82](https://linear.app/melato/issue/MEL-82/f07-b-enforce-aggregate-local-generation-png-cache-budget), child of F07/MEL-61.
- Base: `5fa5292` on `feat/region-aware-studio`; isolated branch `work/mel-82-generation-cache-budget`.
- Scope: backend PNG publication, existing CLI/server configuration, queue recovery and protocol regressions. No change to base selection, texture prompts, masks, blending or protected pixels.

## Implementation

The backend defaults to a 2 GiB PNG payload cap per cache directory. A SQLite
write transaction serializes size accounting and publication across callers.
Existing `.png` and `.pending` payloads count even without ledger records. New
output uses the existing bounded RGB PNG encoder, then an atomic replacement;
failed staging is removed. Existing files and run identities are not evicted.
Hash-verified cache hits work at capacity. A quota-rejected result keeps the
original prompt ID and is retrievable on resume after increasing the limit.
Studio reports `needs_review` without committing a new job revision.

The CLI uses `--cache-mib`; the optional Studio worker uses
`--generation-cache-mib`. Same-directory callers must agree on the cap.

## Verification and limits

- Initial focused protocol/queue run: 14 backend + 16 queue tests passed. Added
  regressions exercise quota exhaustion, existing cache hits, orphan/staging
  accounting, concurrent independent backend connections and same-run recovery.
- Studio HTTP integration and static smoke scripts passed.
- Python compilation, backlog JSON parsing and whitespace checks passed.
- Broad unittest discovery: initial run passed 237 cases but reported five
  E2E-module import errors due to missing pytest; after installing the missing
  test dependency, all 237 unittest cases passed (62.303 s). This does not
  execute standalone pytest E2E functions. No live GPU work or paid inference.
- Merge simulation with concurrent browser-acceptance branch `1b52859` passed.

This is E1 local fixture/protocol evidence only. The cap covers PNG payloads, not
SQLite, filesystem allocation overhead, other cache directories, remote worker
files or process RSS. Reducing a cap does not erase existing files. Automated
retention and archival policy remain open; remote history can expire before a
blocked output is retrieved, and no such expiry authorizes a second submission.
F07 live worker/device acceptance and release approval remain open.
