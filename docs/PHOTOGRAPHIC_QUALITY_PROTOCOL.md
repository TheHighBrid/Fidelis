# Photographic restoration quality protocol (Bot 05)

Protocol ID: `fidelis.photographic_restoration_protocol` · Version: `1.0.0`

## Intent

Fidelis restores photographic credibility. **Sharpness is never a substitute for
restoration quality.** This protocol is the repeatable comparison contract for
skin, hair, textiles, products, and lettering. It complements the F12-A / MEL-79
rights-and-ROI corpus manifest; it does not replace creative acceptance (E3) or
release signoff (E4).

## What this is / is not

| Is | Is not |
| --- | --- |
| E1 structural/protocol evidence | Creative acceptance or competitor parity |
| Defect flags for plastic skin, exaggerated texture, invented product detail, lettering mutation | Fabricated LPIPS / Clarity / Krea scores |
| Bot 04 texture-candidate evaluation hooks | Texture model implementation (Bot 04 lane) |
| Synthetic CI fixtures under `tests/fixtures/photographic_protocol/` | The production rights-cleared 60-case corpus |

## Rubric categories

1. **Skin** — mid-frequency grain must survive; waxy/plastic smoothing fails even when edges look crisp.
2. **Hair** — strand continuity without glitter noise that only raises high-frequency energy.
3. **Textiles** — weave direction/period stays coherent; invented checkerboards fail.
4. **Products** — seams/hardware/contours must not gain new features absent from the base.
5. **Lettering** — glyph geometry stays registered; sharpness that rewrites characters fails.

Cross-cutting rule: a rise in Laplacian/edge energy without mid-band fidelity or
gradient coherence is `sharpness_without_restoration`.

## Corpus relationship

- Frozen 60-slot inventory: `experiments/corpus_manifest.json` (see `docs/CORPUS_MANIFEST.md`).
- Melato production inventory (97 off-repo masters): `experiments/melato_corpus_manifest.json`.
- AI/synthetic Melato assets (`*_2K*`, `file_0000*`) are `non_ground_truth` and must never be used as restoration ground truth.
- Tracked crops/fixtures stay `counts_toward_60_case_corpus: false`.
- Owner GO (via Huncho, 2026-11-19) vouched Melato rights; masters stay off-repo (see `docs/CORPUS_ACQUISITION_PROPOSAL.md`).

## Commands

```bash
.venv/bin/python scripts/validate-corpus-manifest.py --verify-files
.venv/bin/python scripts/validate-corpus-manifest.py --verify-files \
  --master-root /workspace/melato-corpus/fidelis
.venv/bin/python scripts/run-photographic-protocol.py --list-rubrics
.venv/bin/python scripts/run-photographic-protocol.py --show-hook-contract
.venv/bin/python scripts/run-photographic-protocol.py \
  --base base.png --candidate candidate.png --category skin \
  --adapter-id bot04.zero_cost.example --json-out receipt.json
.venv/bin/python -m unittest tests.test_corpus_manifest tests.test_photographic_protocol -v
```

Exit codes for the protocol CLI: `0` PASS, `1` WARN, `2` FAIL.

## Bot 04 plug-in

Bot 04 should call `fidelis.eval.texture_eval_hooks.evaluate_texture_candidate` with
`TextureEvalRequest(base_path=..., candidate_path=..., category=..., adapter_id=...)`
and archive the JSON receipt. Do not mark `is_production_corpus` until the matched
`case_id` is rights-cleared and `available` in the corpus manifest.
