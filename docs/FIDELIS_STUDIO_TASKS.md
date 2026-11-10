# Fidelis Studio task ledger

Updated 2026-11-10. Canonical scope and task definitions:
[execution plan](FIDELIS_STUDIO_PLAN.md).

## Current milestone

M0 foundation implemented. No new diffusion backend, auto segmentation or browser
brush editor is claimed. Existing inference and UI remain available unchanged.

| Task | Status | Evidence / next deliverable |
| --- | --- | --- |
| F01 Audit and publish plan | Complete | `FIDELIS_STUDIO_PLAN.md`, baseline `0f10ca6`, primary references and corrected claims |
| F02 Region compositor | Complete | `fidelis/postprocess/regions.py`; explicit confidence, normalized overlap, linear-light blending, exact locks |
| F03 File reblend and recipe | Complete | `scripts/reblend-regions.py`; verified PNG export, hashes and unsigned recipe; `REGION_REBLEND.md` |
| F04 Artifact contracts and budget storage | Next | Versioned persisted artifacts/masks, cache byte budget and restart tests |
| F05 Runtime/model registry audition | Planned | Installed capability versus candidate distinction and base-model evidence |
| F06 Pinned generation adapter | Planned | Live GPU/schema test required, mocks alone insufficient |
| F07 Durable queue and reconciliation | Planned | Restart/cancel/ambiguous provider result checks |
| F08 Region brush and reblend UI | Planned | Editable masks, undo, touch, preview revisions |
| F09 Segmentation audition | Planned | License clearance and annotated boundary evaluation |
| F10 Structural ROI protection | Planned | Explicit logo/seam/hardware masks and drift screening |
| F11 Colour-managed export | Planned | Alpha, ICC, precision path, export round-trip tests |
| F12 Corpus and comparator tooling | Planned | 60 licensed/consented cases, frozen 30/30 split |
| F13 Calibration and blind acceptance | Planned | Actual Clarity/Krea comparisons and category defect report |
| F14 Batch resilience | Planned | Bounded scheduling and resumable manifests |
| F15 UI polish and packaging | Planned | Real device, accessibility, upgrade and rollback evidence |
| F16 Production release | Planned | Quality and operational gates pass before parity claim |
| F17 Optional challengers | Deferred | Separate FLUX/SUPIR/self-hosted adapter after core release |

## Verification completed

Environment: Linux x86_64, Python 3.12 project `.venv`, NumPy 2.3.5,
OpenCV headless 5.0.0.93. No model weights or paid cloud inference used.

- `.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v`:
  **26 passed**, including seven new compositor/CLI tests and existing tiler,
  streamed tiler, CLI inference-contract and optional face-detector regressions.
- `PATH="$PWD/.venv/bin:$PATH" bash tests/smoke-test.sh`: passed.
- `git diff --check`: passed.
- New regional tests added to the existing Linux/macOS GitHub Actions matrix.
  Remote CI result is separate from these local results.

The new tests verify routing and exact pixel preservation, not realistic texture
generation. No benchmark preference, M1/Android latency, or commercial parity
results have been measured in this batch. Full-frame composition is not yet a
memory-bounded 8K preview solution. The first CLI supports only untagged 8-bit
sRGB RGB PNG inputs and explicit NPZ masks; limitations are documented.

## Next execution batch

F04: define persisted image/mask/recipe contracts, enforce byte budgets and make
reblend reloadable after process restart. Then integrate F08 editing against those
contracts, while F05/F06 establish one genuinely runnable texture backend.
No owner intervention is required for these engineering tasks. Real competitor
outputs and production benchmark selection become a later evidence checkpoint.
