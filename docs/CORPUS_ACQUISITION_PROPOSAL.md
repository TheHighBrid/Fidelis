# Rights-cleared corpus acquisition proposal (BLOCKED on creative approval)

Status: **BLOCKED — route creative approval to Huncho** before committing any real
fashion, portrait, or product photographs.

Bot 05 (photographic quality) prepared the protocol, 60-slot manifest, and
synthetic CI fixtures. Real corpus population is intentionally **not** started
without owner/orchestrator creative approval.

## Proposed production corpus (unchanged F12 target)

| Category | Slots | Calibration | Held-out | Model release |
| --- | --- | --- | --- | --- |
| portraits | 12 | 6 | 6 | required |
| apparel_model | 12 | 6 | 6 | required |
| textiles | 12 | 6 | 6 | not required |
| macros | 12 | 6 | 6 | not required |
| packshot_edge | 12 | 6 | 6 | not required |

Exact slot IDs live in `experiments/corpus_manifest.json`.

## Acceptable license classes (proposal)

Only images that are **clearly licensed for this use** may be promoted to
`availability: "available"`:

1. Owner/Melato original photography with written consent / model release when people appear.
2. Explicitly licensed stock with commercial + AI/derivative terms that cover restoration benchmarking and public evidence screenshots.
3. Public-domain / CC0 works where attribution and source URL are recorded and no third-party trademarked product packaging creates unresolved rights risk.

Unacceptable without written clearance: random web scrapes, social screenshots,
unclear “editorial only” stock, or any asset whose license forbids derivatives /
benchmark publication.

## Required per-asset record

For every promoted case:

- `rights.cleared: true`
- `permission_basis` and `license_id`
- `model_release_verified` when `model_release_required`
- repository-relative `source.relative_path`, SHA-256, dimensions
- normalized `critical_rois` and `known_text` where logos/type exist
- source URL + attribution string in `rights.notes` (or sidecar)

Validate with:

```bash
.venv/bin/python scripts/validate-corpus-manifest.py --verify-files
```

## Ask for Huncho / owner

1. Approve the license classes above (or amend them).
2. Approve whether Melato studio originals, licensed stock, CC0, or a mix will seed the first 60.
3. Authorize storage location for full-resolution masters (repo LFS vs private object store).
4. After approval, Bot 05 populates cleared slots and re-runs protocol + manifest validation — still without fabricating quality scores.

Until then, only synthetic protocol fixtures and the empty 60-slot inventory ship.
