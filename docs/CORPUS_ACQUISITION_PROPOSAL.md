# Rights-cleared corpus acquisition (Melato GO 2026-11-19)

Status: **OWNER GO via Huncho** — Mohamed vouched all **97** Melato images under
`/workspace/melato-corpus/fidelis` as cleared/licensed
(`permission_basis: owner_melato_vouched_2026-11-19`).

Bot 05 inventories those masters **off-repo** (metadata only in git). Image binaries
and Git LFS are intentionally not committed.

## Production corpus targets (unchanged F12 structure)

| Category | Slots | Calibration | Held-out | Model release |
| --- | --- | --- | --- | --- |
| portraits | 12 | 6 | 6 | required |
| apparel_model | 12 | 6 | 6 | required |
| textiles | 12 | 6 | 6 | not required |
| macros | 12 | 6 | 6 | not required |
| packshot_edge | 12 | 6 | 6 | not required |

Exact slot IDs live in `experiments/corpus_manifest.json`. Full Melato inventory:
`experiments/melato_corpus_manifest.json`.

## Storage decision (approved)

- **Masters:** private / off-repo on the Bot 05 box (`FIDELIS_MELATO_MASTER_ROOT`,
  documented path `/workspace/melato-corpus/fidelis`).
- **Git:** commit only manifest metadata (sha256, dimensions, category, split, ROIs,
  known_text, notes). **No image binaries. No LFS.**

## Ground-truth policy

1. Tag AI-generated assets (`*_2K*`, `file_0000*`, plus any judged synthetic) with
   `synthetic: true` / `ground_truth_eligible: false` / `set: "non_ground_truth"`.
2. Protocol and Bot 04 hooks **refuse** those assets as restoration ground truth
   (they may still have calibration/held_out splits for detection evaluation).
3. Flag trademark-heavy cases (Nike box, Mazda interiors, Adidas apparel, etc.) in
   `rights.notes`.
4. Portraits/apparel: `model_release_verified: true` with notes that release is
   owner-vouched.
5. Do **not** fabricate quality/defect scores.

## Validate

```bash
.venv/bin/python scripts/validate-corpus-manifest.py --verify-files
.venv/bin/python scripts/validate-corpus-manifest.py --verify-files \
  --master-root /workspace/melato-corpus/fidelis
```
