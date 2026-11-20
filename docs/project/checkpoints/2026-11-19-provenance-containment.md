# F05-B / MEL-75: model provenance containment

- Base: integration PR #64, `b03100192544024f56646c91ee560b8857de7e1c`.
- Scope: model-provenance validation and the read-only capability inventory.
  No model selection, inference, image processing, or storage schema changes.
- Catalog inputs now reject noncanonical local paths, nonportable separators,
  traversal, duplicate TSV identities, and pinned runtime status without an
  archive digest. Weight keys must be individual filenames.
- Static symlink escapes from the selected app home are rejected before reads
  and hashing. The inventory validates its provenance inputs first; escaped
  registered-model metadata/weights are reported as invalid metadata.
- This is not an OS sandbox or a protection against a concurrent hostile local
  filesystem mutation. The app home remains an operator-controlled directory.
- Local verification: 10 model-provenance tests, 8 worker-preflight tests,
  Python compileall and `git diff --check` passed against the isolated checkout.
  Full CI and GPU/device/terms acceptance remain separate gates.
- No checkpoint downloads, external image uploads, or paid execution.

Next: review into the integration branch; finish real worker qualification and
commercial terms review before promoting any new model.
