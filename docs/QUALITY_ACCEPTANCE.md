# Held-Out Quality Acceptance Protocol (`F13` / `MEL-66`)

Fidelis Studio's held-out quality acceptance evaluator (`fidelis/eval/quality_acceptance.py`
and `scripts/evaluate-quality-acceptance.py`) enforces the gate order and threshold
protocol defined in [QUALITY_GATES.md](project/QUALITY_GATES.md):

1. **Reproducibility Receipt Completeness**: Every evaluation submission must carry a
   complete `reproducibility_receipt` (`code_sha`, `corpus_lock_sha256`,
   `calibration_recipe_sha256`, `runtime_versions`, `model_weight_hashes`, `seed_policy`,
   and `colour_path`). Unsigned execution records must never claim `c2pa_verified`.
2. **Calibration Freeze & Split Isolation**: Tuning is restricted to the 30 `calibration`
   slots. Any `calibration` slot appearing in `held_out_ballots` triggers
   `split_contamination_detected` and fails closed.
3. **Zero Critical Fidelity Defects**: Any confirmed critical defect (`identity_drift`,
   `text_logo_corruption`, `seam_zipper_hardware_mutation`,
   `garment_construction_mutation`, `product_geometry_mutation`,
   `protected_pixel_violation`, `internal_registration_drift`,
   `plastic_skin_or_beauty_smoothing`, or `background_hallucination`) fails acceptance.
4. **Blind Pairwise Thresholds & Confidence Intervals**:
   - Per comparator target (`pinned_clarity`, `dated_krea`):
     `preference_plus_ties_rate >= 0.80` and `win_rate >= 0.50`.
   - Per category (`portrait`, `model_apparel`, `textile`, `macro`, `packshot_edge` — at
     least 6 distinct held-out cases each): `preference_plus_ties_rate >= 0.60`.
   - Reports exact Wilson 95% confidence intervals and deterministic percentile bootstrap
     95% confidence intervals alongside sample sizes, plus inter-rater agreement
     (`cohen_kappa` and `krippendorff_alpha_nominal`) when `reviewer_id` is supplied across
     overlapping dual-reviewer ballots.
5. **Owner Creative Signoff**: When all quantitative gates pass but
   `owner_creative_signoff.status != "approved"`, `overall_status` is capped at
   `awaiting_owner_signoff`.

## CLI Usage

```bash
# Evaluate a blind held-out quality submission
.venv/bin/python scripts/evaluate-quality-acceptance.py \
  path/to/held-out-submission.json \
  --output .cache/quality-acceptance-report.json

# Require explicit owner creative signoff (exits 2 if status is awaiting_owner_signoff)
.venv/bin/python scripts/evaluate-quality-acceptance.py \
  path/to/held-out-submission.json \
  --require-owner-signoff
```

## Evidence Boundary

- **Implemented & unit-tested**: Reproducibility receipt validation, split-contamination
  guard, critical defect gate, Wilson/bootstrap 95% confidence intervals, per-target and
  per-category threshold enforcement, and owner signoff gating
  (`tests/test_quality_acceptance.py`).
- **Pending external verification (`F13` remains `In Progress` / `partial`)**:
  Cleared 60-case production corpus assets, live Clarity/Krea comparator outputs, human
  blind review ballots, and final owner creative signoff.
