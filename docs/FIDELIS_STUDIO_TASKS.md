# Fidelis Studio task ledger

Updated 2026-11-10. Canonical scope and task definitions:
[execution plan](FIDELIS_STUDIO_PLAN.md).

## Current milestone

M0 foundation and F04 persistent artifacts implemented. F08 review/sliders/comparison
UI started at `/regions`; brush editing is still planned. No new diffusion backend
or automatic segmentation is claimed. Existing inference routes remain intact.

| Task | Status | Evidence / next deliverable |
| --- | --- | --- |
| F01 Audit and publish plan | Complete | `FIDELIS_STUDIO_PLAN.md`, baseline `0f10ca6`, primary references and corrected claims |
| F02 Region compositor | Complete | `fidelis/postprocess/regions.py`; explicit confidence, normalized overlap, linear-light blending, exact locks |
| F03 File reblend and recipe | Complete | `scripts/reblend-regions.py`; verified PNG export, hashes and unsigned recipe; `REGION_REBLEND.md` |
| F04 Artifact contracts and budget storage | Complete | SQLite versioned manifests, immutable checksummed disk artifacts, byte caps, stripe composition, restart/conflict/failure tests |
| F05 Runtime/model registry audition | Next | Installed capability versus candidate distinction and base-model evidence |
| F06 Pinned generation adapter | Planned | Live GPU/schema test required, mocks alone insufficient |
| F07 Durable queue and reconciliation | Planned | Restart/cancel/ambiguous provider result checks |
| F08 Region brush and reblend UI | In progress | Saved review at `/regions`, blend controls, comparison and export implemented; painting, undo/redo and visual device review remain |
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
  **44 passed**, covering compositor/CLI, persistent job storage, concurrent revision
  conflict, failed-render rollback, schema/checksum/budget validation, HTTP import/
  reopen/reblend/export, request isolation, malformed mask headers, existing tilers
  and optional face-detector regressions.
- `PATH="$PWD/.venv/bin:$PATH" bash tests/smoke-test.sh`: passed.
- Existing `tests/test-web-ui.sh` HTTP inference integration: passed.
- Regional UI JavaScript `node --check`: passed.
- `git diff --check`: passed.
- New regional tests added to the existing Linux/macOS GitHub Actions matrix.
  Remote CI result is separate from these local results.

The new tests verify routing and exact pixel preservation, not realistic texture
generation. No benchmark preference, M1/Android latency, or commercial parity
results have been measured in this batch. The persistent store now composes disk mappings in bounded stripes and streams PNG
export, but total-process memory including import decoding is not certified for
8K on the M1. Inputs remain untagged 8-bit sRGB RGB PNGs with explicit NPZ masks.
Browser visual review was blocked by the browser-to-local-server connection; HTTP
flow and JavaScript syntax verification succeeded. See `REGIONAL_WORKSPACE.md`.

## Next execution batch

F05: audit installed model/runtime capabilities and pin one runnable texture
backend through F06. Continue F08 with editable region masks and undo/redo against
the persistent job/revision contracts. Real competitor outputs and production
benchmark selection remain later evidence checkpoints. No paid calls or model
quality certification were part of this batch.
