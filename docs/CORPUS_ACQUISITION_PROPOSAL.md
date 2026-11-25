# Rights-cleared corpus acquisition (Melato GO 2026-11-19)

Status: **APPROVED — Melato-first / off-repo** (owner GO via Huncho, 2026-11-19).
Mohamed vouched all **97** Melato images under `/workspace/melato-corpus/fidelis`
as cleared/licensed (`permission_basis: owner_melato_vouched_2026-11-19`).

Bot 05 inventories those masters **off-repo** (metadata only in git). Image binaries
and Git LFS are intentionally not committed. Textiles/macros specialty gaps in the
frozen 60 stay **open** (do not invent fills). Real Madrid jersey stays unflagged
until a specific filename is named.

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

## Open gaps (intentional)

- Frozen 60 readiness: **42 available / 18 missing** (`calibration 21/30`,
  `held_out 21/30`: `portraits 10/12`, `apparel_model 8/12`, `textiles 6/12`,
  `macros 9/12`, `packshot_edge 9/12`) after Melato-first fill, the 2026-11-25
  eligibility/construction audits (#122, #123), and 12 visually inspected
  CC0/Public-Domain off-repo photographs (Wikimedia Commons, Metropolitan Museum,
  Cleveland Museum of Art, Cooper Hewitt).
- Prefer leaving remaining specialty/released slots **missing** over forcing
  AI, unverified-release portraits, or weak subject matches into ground-truth slots.
- If Mohamed adds more cleared masters later, slot them into remaining intents.
- Trademark notes cover Nike / Mazda / Adidas / etc.; Real Madrid remains unflagged
  until Huncho names a filename.

