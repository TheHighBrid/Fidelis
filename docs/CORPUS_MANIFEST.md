# Corpus rights, split, and ROI manifest (`F12-A` / `MEL-79`)

`experiments/corpus_manifest.json` defines the frozen **60-case benchmark structure**
(`30` calibration / `30` held-out) required before calibration tuning (`F13`) and
regression-free parity claims (`F16`).

Companion Melato production inventory: `experiments/melato_corpus_manifest.json`
(all **97** owner-vouched masters). Image binaries stay **off-repo** (no git, no LFS).

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

Promoting a slot to `availability: "available"` requires:

1. Explicit `rights.cleared: true`, non-empty `permission_basis`, and `license_id`
   (plus `model_release_verified: true` whenever `model_release_required: true`).
2. Identity of the master:
   - **In-repo:** repository-relative `source.relative_path` (no absolute paths or `..`),
     64-character lowercase `source.sha256`, and positive integer pixel dimensions; **or**
   - **Off-repo Melato:** `source.storage: "off_repo"`, `source.filename`, sha256, dims,
     `relative_path: null`. Masters are resolved locally via `--master-root` /
     `FIDELIS_MELATO_MASTER_ROOT` when verifying bytes; CI without masters still validates
     schema/rights and skips byte checks. Filenames must be single portable names, not
     paths, even in metadata-only mode; symlinks resolving outside the selected master
     root are refused when checking files.
3. No duplicate `sha256` across available cases or across `calibration` vs `held_out` splits.
4. Non-empty `critical_rois`. Normalized `bbox_norm` is required for in-repo available
   cases; off-repo Melato fills may keep `bbox_norm: null` until annotated (prefer null
   over invented boxes). Document `known_text` where typography/logos exist.
5. Neither in-repo nor off-repo available slots may be marked synthetic, non-GT,
   or explicitly ineligible for restoration ground truth.

## Melato companion (97 assets)

- Masters live only on the Bot 05 box under `/workspace/melato-corpus/fidelis`
  (documented path; not committed).
- `permission_basis`: `owner_melato_vouched_2026-11-19`.
- AI/synthetic name patterns (`*_2K*`, `file_0000*`) are forced into
  `set: "non_ground_truth"` with `synthetic: true` and `ground_truth_eligible: false`.
  Protocol/hooks refuse using them as restoration ground truth.
- Trademark-heavy cases (Nike, Mazda, Adidas, etc.) record flags in `rights.notes`.
- Portraits/apparel record `model_release_verified: true` as owner-vouched.

## Validate locally

```bash
# CI / schema path (no Melato masters required)
.venv/bin/python scripts/validate-corpus-manifest.py --verify-files

# Local box with Melato masters present
.venv/bin/python scripts/validate-corpus-manifest.py --verify-files \
  --master-root /workspace/melato-corpus/fidelis
```

Validation exits non-zero if rights are incomplete, in-repo image bytes/dimensions
mismatch, splits drift from `30/30`, or calibration images leak into `held_out`.

## Bot 05 photographic protocol (2026-11-19)

Companion evaluation lives in `docs/PHOTOGRAPHIC_QUALITY_PROTOCOL.md` and
`fidelis/eval/photographic_protocol.py`. Synthetic CI fixtures under
`tests/fixtures/photographic_protocol/` exercise defect detection only; they do
**not** fill any of the 60 production slots. Melato AI/synthetic assets are likewise
never restoration ground truth.
