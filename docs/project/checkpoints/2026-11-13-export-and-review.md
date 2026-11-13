# Export, batch and PR review checkpoint

Base `56a0078`, PR #12. F11 / MEL-65 owns precision and colour export. F14 /
MEL-67 owns saved batch export. Scope covers the regional compositor, PNG codec,
CLI and startup/run identity review fixes.

- RGB16 and straight-alpha PNGs round-trip through the reblend CLI. Independent
  OpenCV decode checks protected RGBA samples, alpha retention and linear-light
  blend results. Embedded RGB8 ICC conversion requires a CLI flag.
- Saved Studio masters export sequentially with revision pins, byte budgets and
  hash-verified continuation. Browser controls for batch creation and model-backed
  batch generation remain open.
- Applied three verified review findings. The RGB8 import paths inspect PNG depth
  before decoding. Legacy routes can run without regional imports. Distinct grids
  get distinct generation IDs and matching legacy runs retain their original ID.
- Browser editor persistence remains RGB8. Native ICC16 and target-device colour
  and memory evaluation remain open.

See [export instructions](../../STUDIO_EXPORT.md). Current runtime doctor finds no
native weight candidate, PyTorch, NVIDIA tooling or reachable ComfyUI worker.
Production quality acceptance still needs live inference and comparison evidence.

## Remaining work sizing

Sizes estimate relative effort for one contributor. Model access, photo
permissions and device availability determine elapsed time for the quality lane.

| Work package | Size | Exit evidence |
| --- | --- | --- |
| Browser managed ingest/export and native precision | L | Editor and CLI agree on colour, alpha and locks |
| Model-backed batch scheduling and recovery | M | Interrupted run resumes against its original worker ID |
| Local worker and checkpoint qualification | L | Provenance, repeatable live output and memory report |
| Corpus freeze and held-out comparison | XL | Rights and ROI inventory plus blind Clarity/Krea results |
| Target packaging, device acceptance and release | L | Clean install, upgrade/rollback and creative approval |

## Verification

136 Python tests passed, along with the web HTTP integration, static smoke
suite, editor/inspector syntax checks and `git diff --check`. The corpus audit
reports eight regression assets and zero eligible production cases out of 60.
The browser connection attempt did not reach the loopback Studio.
