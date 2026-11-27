# Historical source-evidence plan & corpus-slot resolution · issue #134 · 2026-11-26

Base: `main` (`7336376`, after PR #141 merged).  
Scope: non-code historical source-evidence plan and corpus-slot resolution protocol
for [GitHub #134](https://github.com/TheHighBrid/Fidelis/issues/134) prior to final
`F13` (`MEL-66`) quality acceptance lock. No frozen manifest splits, acceptance
thresholds, model weights, or retained artifacts were modified.

## 1. Preflight & ledger basis

Running `scripts/check-source-split-isolation.py --manifest experiments/corpus_manifest.json --manifest experiments/melato_corpus_manifest.json`
at `7336376` reports:

- `status`: `blocked` (`passed: false`)
- `unique_source_hashes`: `113`
- `conflict_count`: `12` (cross-split SHA-256 disagreements between `frozen60` and `approved97`)
- `unknown_hash_count`: `14` (unpopulated `missing` slots in `experiments/corpus_manifest.json`)
- `error_count`: `0`

Cross-referencing the 19 retained audition reports (`32` source references) in the
off-repo split audit (`~/melato-corpus/fidelis/release-evidence/split-audit/findings.md`
and `audition-source-ledger.json`) classifies every conflict and missing slot below.

## 2. Exact 12 cross-split source-SHA conflicts

| Frozen60 `case_id` | Frozen split | Approved97 `asset_id` | Approved97 split | Source SHA-256 | Retained audition cross-role exposure |
| --- | --- | --- | --- | --- | --- |
| `por_medium_skin_daylight` | `calibration` | `mel_074` | `held_out` | `4c5bcc3278d6a4f9d34ce4649d0c778e3afadbc741a1ba6edb3c3ec79aec0746` | None observed in retained ledger |
| `por_olive_shallow_dof` | `calibration` | `mel_037` | `held_out` | `8e98050e6be5b04e6e1a1b07ea2e68f75a6760ab40bb2efb6b235e773d07adac` | None observed in retained ledger |
| `por_warm_mixed_tungsten` | `calibration` | `mel_091` | `held_out` | `e8a1cd49b4cbf7de630ed0503136f61918b94b5ae647b07ae130d36880572332` | None observed in retained ledger |
| `por_held_east_asian_softbox` | `held_out` | `mel_035` | `calibration` | `22c924b9b09878d0490995ecbe076cca58444ba281c3055e1235939023856dab` | None observed in retained ledger |
| `por_held_group_dual_focus` | `held_out` | `mel_024` | `calibration` | `06f684840caebd9b47e7c98b1d17a6619139a19f1d81bdcf2ce9992721a2b206` | None observed in retained ledger |
| `por_held_high_iso_backstage` | `held_out` | `mel_014` | `calibration` | `bd1249a6e7ea02a231d199035a578d1b391815f8e57389aec2de1c28ebacb91b` | **Confirmed cross-role exposure** (5 runs) |
| `app_silk_slip_drape` | `calibration` | `mel_070` | `held_out` | `c5471a9ba73b4d018b0ce7abad9401f2d02d62c3bb119cdd7537c467adb74143` | None observed in retained ledger |
| `app_graphic_tee_screenprint` | `calibration` | `mel_089` | `held_out` | `a9cebb58ba1cb551eae0f5482bab73c643ca0ecaca1a112b5a5b565fe025ebac` | None observed in retained ledger |
| `tex_raw_indigo_denim` | `calibration` | `mel_041` | `held_out` | `b39386120a5a22cf9795c279506f35966a22bb7aab5b2f5466d8b7cfd4047e5c` | None observed in retained ledger |
| `mac_held_chain_strap_links` | `held_out` | `mel_025` | `calibration` | `c33ba7303890cab25d0cf9bd63ba3e194ecd9464a2ed5dc5339ccc230b549377` | None observed in retained ledger |
| `pak_clear_perfume_flacon` | `calibration` | `mel_045` | `held_out` | `4fd7c4b30a8b6a85a9b038fb92a601fde7cdb95c7131240593b12ffb3a9da33d` | None observed in retained ledger |
| `pak_matte_box_packaging` | `calibration` | `mel_054` | `held_out` | `78b282a7fc8e51e911afb54b26f71dd8f5968baac903b5111c287b3dad5755bd` | None observed in retained ledger |

## 3. Retained exposure findings (preserve evidence, qualify scope)

1. **Confirmed cross-role calibration + held-out exposure (`por_held_high_iso_backstage` / `mel_014`, `4cf38666019303d6e0195054fc3b684e.jpg`):**
   - Calibration runs precede held-out evaluations in retained metadata:
     - `release-evidence/d6f420cc/mel014-calibration/audition_report.json` (`RealeSR-general-v3`, `calibration`, `2026-11-25T00:35:00.825525+00:00`, `FAIL_SMOOTHING_REGRESSION`)
     - `release-evidence/7d97abd/corpus-heldout-realesr/audition_report.json` (`RealeSR-general-v3`, `held_out`, `2026-11-25T03:18:07.816019+00:00`, `FAIL_SMOOTHING_REGRESSION`)
     - `release-evidence/7d97abd/melato-8-masters-realesr/audition_report.json` (`RealeSR-general-v3`, `calibration`, `2026-11-25T03:52:15.201308+00:00`, `PASS_MATERIAL_DETAIL`)
     - `release-evidence/model-candidates/swinir-light-x4/audition/audition_report.json` (`SwinIR-lightweight-DIV2K-x4`, `calibration`, `2026-11-25T05:14:13.315170+00:00`, `PASS_MATERIAL_DETAIL`)
     - `release-evidence/b865815/f12-heldout-6-realesr/audition_report.json` (`RealeSR-general-v3`, `held_out`, `2026-11-25T06:00:26.763431+00:00`, `FAIL_SMOOTHING_REGRESSION`)
   - **Rule:** Retain all image outputs, failure outcomes, timings, and protected-pixel
     records as diagnostic evidence. **Disqualify** `bd1249a6...` as untouched
     held-out evidence for `RealeSR-general-v3`, `SwinIR-lightweight-DIV2K-x4`,
     or any recipe calibrated against `mel_014`. Never silently relabel the report ID.

2. **Repeated held-out diagnostic runs (`por_held_glasses_reflection` / `mel_056`, `IMG_0932.jpg`, SHA-256 `6a466d2f233f91fa2d0d2bf3e18a2879ba00d1066869d743350aae66a09df79f`):**
   - Evaluated repeatedly under `held_out` aliases (`d6f420cc/IMG_0932`, `7d97abd/corpus-heldout-realesr`, `7d97abd/melato-8-masters-realesr`, `b865815/f12-heldout-6-realesr`, each `FAIL_SHARPENING_ONLY` with `RealeSR-general-v3`).
   - **Rule:** Preserve as held-out diagnostic failure evidence; do not count repeated
     diagnostic runs as a once-only untouched held-out acceptance study unless owner
     approves slot replacement or explicit diagnostic disclosure before F13 lock.

## 4. Required pre-F13 resolution steps (owner/corpus gate)

1. **Resolve the 12 manifest split-label disagreements without silent edits:**
   - Treat `experiments/corpus_manifest.json` (`frozen60`) as the canonical F13 split
     contract.
   - For the 11 unexposed disagreements (`por_medium_skin_daylight`, `por_olive_shallow_dof`,
     `por_warm_mixed_tungsten`, `por_held_east_asian_softbox`, `por_held_group_dual_focus`,
     `app_silk_slip_drape`, `app_graphic_tee_screenprint`, `tex_raw_indigo_denim`,
     `mac_held_chain_strap_links`, `pak_clear_perfume_flacon`, `pak_matte_box_packaging`),
     reconcile provisional `split` labels in `experiments/melato_corpus_manifest.json`
     to match `frozen60` with explicit owner signoff, OR exclude `approved97` from the
     F13 preflight once `frozen60` is 60/60 self-contained.
   - For `por_held_high_iso_backstage` / `mel_014` (and optionally `por_held_glasses_reflection` / `mel_056`),
     either replace the held-out `frozen60` slot with a fresh, unexposed Melato
     portrait (`model_release_verified: true`) before final held-out inference, or
     document explicit held-out exclusion so `scripts/evaluate-quality-acceptance.py --manifest`
     cannot pass contaminated ballots.
2. **Restore missing off-repo calibration master (`por_deep_skin_studio` / `mel_032`):**
   - `648676378_1791816552214174.jpg` (SHA-256 `58e9638f46c07c611b7305d2684ff7bafe0b34fa1aafcd8a360715671604e573`)
     is absent from local `/Users/tyf12/melato-corpus/fidelis` and connected Drive
     searches (`corpus-recovery-2026-11-24.md`), causing `validate-corpus-manifest.py --verify-files`
     to fail. Recover the exact master bytes from the original Bot 05 workspace or
     approve a replacement calibration portrait.
3. **Resolve the 14 missing slots in `experiments/corpus_manifest.json` (`46/60` filled):**
   - `6` slots require `model_release_required: true`: `por_fair_freckles_closeup`,
     `por_elderly_character_lines`, `app_sheer_organza_overlay`, `app_held_trench_epaulette`,
     `app_held_sequin_evening`, `app_held_herringbone_coat`.
   - `8` specialty non-model-release slots: `tex_held_merino_rib`, `tex_held_technical_ripstop`,
     `mac_engraved_clasp_bevel`, `mac_held_concealed_nylon_zip`, `mac_held_chain_embroidery`,
     `mac_held_watch_buckle_pin`, `pak_alpha_cutout_sneaker`, `pak_held_white_shirt_shadow`.
   - A 2026-11-26 audit across Wikimedia Commons, Openverse (`cc0,pdm`), Cleveland
     Museum of Art Open Access, and Poly Haven confirmed zero spec-compliant matches
     without relaxing fiber, construction (`2x2` merino rib, `ripstop` grid, invisible
     coil zipper in silk crepe, `MLT` chain-stitch on fleece, `SWISS` brushed steel
     tang buckle, alpha cutout sneaker, ghost-mannequin poplin shirt), or model-release
     criteria. Slots remain intentionally `missing` until owner supplies cleared
     Melato assets or amends slot scope.
