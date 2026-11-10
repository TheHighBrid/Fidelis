# Fidelis

Photographic restoration for fashion, portraits and product imagery. Fidelis aims
to add believable detail while preserving identity, garment construction, logos,
hardware, colour, lighting and depth of field.

**Current stage: engineering alpha. Competitive parity is not established.**
The target combines Clarity-style controlled texture reconstruction with editable
regional protection inspired by the requested Krea workflow. That is a product
objective, not a claim of equivalent output today.

## Start here

| Reader | Read first |
| --- | --- |
| New developer or AI agent | [Onboarding](ONBOARDING.md), [agent directives](AGENTS.md), [handoff](docs/project/HANDOFF.md) |
| Product/design contributor | [Vision and final product](docs/project/VISION.md), [blueprint](PLAN_BLUEPRINT.md) |
| Contributor choosing work | [Current status](docs/project/STATUS.md), [roadmap](docs/project/ROADMAP.md), [Linear project](https://linear.app/melato/project/fidelis-studio-a057f366fa71) |
| Reviewer | [Contribution workflow](CONTRIBUTING.md), [quality gates](docs/project/QUALITY_GATES.md), [known risks](docs/project/RISKS.md) |
| Maintainer | [Architecture](docs/project/ARCHITECTURE.md), [collaboration](docs/project/COLLABORATION.md), [decisions](docs/project/DECISIONS.md) |

The complete reading map is in [docs/README.md](docs/README.md).

## Branch and release reality

The audited baseline on `main` is `0f10ca6`. The Studio implementation is on
`feat/region-aware-studio`, code snapshot `5f32fba`, in [PR #12](https://github.com/TheHighBrid/Fidelis/pull/12).
Documentation may be published on `main` before that code merges. Checkout the
Studio branch to use its editor/backend modules. A package version string or a
historical changelog entry is not proof of production readiness.

| Implemented in the Studio branch | Still needs acceptance or implementation |
| --- | --- |
| Linear-light composition with exact protected base pixels | Live model/workflow quality validation |
| Persistent jobs, checksums, revisions and storage limits | Asynchronous inference queue and cancellation |
| Protect/skin/hair/fabric painting, erase and unsaved undo/redo | Visual/device acceptance and native-pixel inspection |
| Regional comparison, preview zoom and PNG export | Automatic confidence-gated segmentation and structural detection |
| Local ComfyUI protocol adapter and resumable run IDs | Colour-managed alpha/high-precision export and benchmark parity |

At `5f32fba`, **62 local Python tests passed**, plus web UI integration, smoke and
JavaScript syntax checks. These establish tested behaviours, not GPU image quality.
The audited development executor has no configured ComfyUI worker/model weights.
The [status ledger](docs/project/STATUS.md) records limits, provenance and next work.

## Development quick start

```bash
git clone https://github.com/TheHighBrid/Fidelis.git
cd Fidelis
git switch feat/region-aware-studio
```

Create a project `.venv` and install the development dependencies as documented in
[Onboarding](ONBOARDING.md). Then:

```bash
.venv/bin/python scripts/web-ui.py --bind 127.0.0.1 --port 8765
```

Open `http://127.0.0.1:8765/regions`. Import aligned, untagged 8-bit sRGB RGB PNG
passes, optionally import NPZ masks, or paint regions from scratch. This path
reblends supplied passes; it does not automatically generate a new texture.

```bash
.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v
.venv/bin/python scripts/backend-doctor.py
```

The doctor reports availability without installing models or submitting generation.
[Regional editing](docs/REGIONAL_WORKSPACE.md) and the [local texture adapter](docs/COMFY_TEXTURE_BACKEND.md)
cover their exact contracts. Never expose the current local studio as a public
service. The explicit loopback bind is required by the current deployment policy.

## Native ARM64 lane

Fidelis retains the NCNN/Vulkan CLI for Android/Termux and the Apple Silicon
runtime work. Generative quality research remains separate from native runtime
certification. Models are candidates until auditioned on the target device.

See [native setup and commands](docs/LEGACY_RUNTIME_GUIDE.md),
[photo-model candidates](docs/PHOTO_MODEL_CANDIDATES.md), and the
[VOSR experiment record](experiments/VOSR_FIDELITY_SWEEP.md). Nomos is not the accepted
final quality target; previous synthetic texture and softened source-fusion results
must not be reintroduced without evidence.

## Product and project records

- [Plan blueprint](PLAN_BLUEPRINT.md): strategy, boundaries and operating model.
- [Detailed execution plan](docs/FIDELIS_STUDIO_PLAN.md): technical assumptions and F01-F17 acceptance scope.
- [Roadmap and checkpoints](docs/project/ROADMAP.md): milestone exit criteria.
- [Linear project](https://linear.app/melato/project/fidelis-studio-a057f366fa71): assignments, dependencies and current coordination.
- [GitHub umbrella #11](https://github.com/TheHighBrid/Fidelis/issues/11), linked to Linear `MEL-53`: cross-system entry point.

GitHub owns versioned specifications, code and evidence; Linear owns coordination.
There is no claimed automatic synchronization of all documents or task state.
No contributor, deadline, meeting or product milestone is invented to fill a board.

Code is under [MIT](LICENSE). Every external runtime/checkpoint/LoRA/segmentation
weight has separate terms that must be verified before distribution or promotion.
