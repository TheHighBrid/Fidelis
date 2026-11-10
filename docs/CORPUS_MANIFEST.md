# Corpus rights, split, and ROI manifest (`F12-A` / `MEL-79`)

`experiments/corpus_manifest.json` defines the frozen **60-case benchmark structure**
(`30` calibration / `30` held-out) required before calibration tuning (`F13`) and
regression-free parity claims (`F16`).

## Separation from regression fixtures

Existing tracked crops (`experiments/eval_crops/*.png`) and synthetic test fixtures
(`tests/fixtures/*.png`) are inventory-tracked under `regression_assets` with their
measured SHA-256 checksums and dimensions, with `counts_toward_60_case_corpus: false`
and `rights_cleared: false`. They do **not** satisfy the 60-case corpus or count as
licensed held-out benchmark images.

## Frozen 60-slot category and split structure

| Category | Total slots | Calibration (`calibration`) | Held-out (`held_out`) | Model release required |
| --- | --- | --- | --- | --- |
| `portraits` | 12 | 6 | 6 | `true` |
| `apparel_model` | 12 | 6 | 6 | `true` |
| `textiles` | 12 | 6 | 6 | `false` |
| `macros` | 12 | 6 | 6 | `false` |
| `packshot_edge` | 12 | 6 | 6 | `false` |
| **Total** | **60** | **30** | **30** | — |

At creation, all **60 benchmark slots** are marked `availability: "missing"` (`0/60`
available). Promoting a slot to `availability: "available"` requires:

1. Explicit `rights.cleared: true`, non-empty `permission_basis`, and `license_id`
   (plus `model_release_verified: true` whenever `model_release_required: true`).
2. A repository-relative `source.relative_path` (no absolute paths or `..` traversal),
   64-character lowercase `source.sha256`, and positive integer pixel dimensions.
3. No duplicate `sha256` across cases or across `calibration` vs `held_out` splits.
4. Non-empty `critical_rois` with valid normalized `[x0, y0, x1, y1]` boxes inside
   `[0, 1]` and documented `known_text` strings where typography/logos exist.

## Validate locally

```bash
.venv/bin/python scripts/validate-corpus-manifest.py --verify-files
```

Validation exits non-zero if rights are incomplete, image bytes/dimensions mismatch
on disk, splits drift from `30/30`, or calibration images leak into `held_out`.
