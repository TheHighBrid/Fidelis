# PR #12 review remediation and evidence receipt

Date: 2026-11-15
Scope: `feat/region-aware-studio` (PR #12), original review head `43abacfc105cf05c8d3cd49ff1a526266eb11577`
Current integrated head: `929334bed65de8db54e4a1bc6732f7176a91c5e6`
Delivery state: merged to Studio feature branch; not merged into main, deployed or released

## Completed review fixes

| PR | Studio squash SHA | Finding resolved | Independent acceptance |
| --- | --- | --- | --- |
| [#17](https://github.com/TheHighBrid/Fidelis/pull/17) | `16e91591` | Required Clarity and Krea comparator evidence cannot be silently omitted | F13 local suite 8/8, Linux/macOS CI, Codex no findings |
| [#18](https://github.com/TheHighBrid/Fidelis/pull/18) | `9d325494` | Without authorized texture ROIs, unknown pixels must stay on precision base | Restoration local 9/9, Linux/macOS CI, Codex no findings |
| [#19](https://github.com/TheHighBrid/Fidelis/pull/19) | `929334be` | Independent candidate and bicubic PNGs, no side-by-side merged image artifacts | Audition 5/5, coffee regression 5/5, Linux/macOS CI, refreshed Codex no findings |
| [#20](https://github.com/TheHighBrid/Fidelis/pull/20) | `419c6d13` | Workflow hash no longer misrepresented as checkpoint-weight SHA-256 | Restoration local 9/9, Linux/macOS CI, Codex no findings |
| [#21](https://github.com/TheHighBrid/Fidelis/pull/21) | `0223951b` | Backup integrity reads actual generation `runs(id,record)` and `tasks(id,record)` schemas | Packaging local 6/6, Linux/macOS CI, Codex no findings |

The five changes were also tested together on a local extracted snapshot: **33 tests plus 4 subtests passed**. Static smoke and web UI server integration passed after restoring the executable bit lost during ZIP extraction. The local Chromium test did not reproduce the prior macOS browser receipt; do not claim physical-device or new browser acceptance from this checkpoint.

## Independent integrated verification

The combined-head PR #12 CI run [43673811216](https://github.com/TheHighBrid/Fidelis/actions/runs/43673811216) must be independently checked before calling its aggregate matrix green. The five individual PR results do not replace combined-head evidence.

## Unresolved gates

- Docker Compose networking sends host-loopback-published requests to a non-loopback container bridge peer. The strict local-request guard rejects them. Do not weaken origin/client checks without an explicit trusted-transport design and actual forwarded-request test.
- Live ComfyUI worker checkpoint and graph provenance, GPU inference and failure recovery need independent E2 evidence. Existing Apple M1 NCNN/segmentation benchmarks do not certify the Comfy lane.
- F12 production corpus requires 60 genuinely rights-cleared photographic cases, evaluated with the frozen calibration/held-out protocol, not synthetic fixtures.
- F13 requires real comparator outputs and blind review; missing paid/commercial access must be recorded, not substituted.
- F08-B physical Android/iOS touch and real visual acceptance remain open, even though same-host Chromium was previously tested.
- PR #12 remains unmerged to main; packaging/deployment and release signoff remain separate E3/E4 decisions.

## Next concrete action

Verify combined-head CI; resolve Compose transport safely with a container-forwarded request test; obtain approved live model and corpus evidence independently; update the canonical status, roadmap and relevant Linear items at each genuinely achieved gate. Avoid duplicate work with open PRs #10, #14 and #16.
