# Repeatable offline preview dependency installation · #147

Base main `2487035`; implementation tested at
`0f5ac9b58e4e9c59ba3305c047378774ecd82b25`. This advances the Python installation
part of F15. Native runtime/model distribution, whole-machine bootstrap and final
release acceptance remain separate.

## Fixed criterion and implementation

From a new extraction and existing compatible Python, install the complete pinned
dependency set using only regular local wheels with matching SHA256 hashes.
Reject unsafe/unpinned locks, missing/tampered/unexpected wheels and existing
environments/evidence before installation. Retain failed attempts. Require local
dependency consistency, scientific/Studio imports and exact installed versions
before reporting `dependency_environment_ready`. Never claim native/model or
production readiness from that status. These criteria were recorded in #147
before testing; no image-quality or corpus criterion changed.

`scripts/install-offline-python.py` uses the stdlib-only
`fidelis/studio/offline_environment.py`. It snapshots a validated lock and invokes
pip with no index/cache, required hashes, wheels only and `--no-deps`. The latter
prevents wheel dependency metadata from introducing direct remote URLs; a local
`pip check` then rejects an incomplete dependency set before import checks.
Inherited pip redirection and Python import-path overrides are removed from
children, which run with `-I`. Subprocesses have a 300-second bound. A failed
environment/log/receipt is retained and cannot be overwritten by a repeat attempt.

The target profile `config/offline/macos-arm64-py312-20261128.txt` records 22 exact
wheel hashes from the earlier verified M1 workflow. It is an engineering preview
profile for the recorded CPython/macOS target, not a universal production lock.
See [offline instructions](../../OFFLINE_PYTHON.md).

## Actual fresh-archive installation and inference

Built and audited both source previews from clean implementation commit `0f5ac9b`:

| Archive | SHA256 |
| --- | --- |
| fidelis-local-preview-0f5ac9b58e4e.tar.gz | 0626e8ed84139bf2c8993c9d12d0c17f8232cd84fda6df68f6b735796b2e1b0a |
| fidelis-local-preview-0f5ac9b58e4e.zip | 1cc8e17eba1567203f9a9a2e3738717a788dfa42bcc5c10231c50f935fae7386 |

Extracted into a new directory and ran the packaged installer using existing
CPython 3.12.16 with stdlib ensurepip on Apple M1/macOS 27.3 arm64. The prepared
wheelhouse contains 22 wheels, 74,071,843 bytes. Wheelhouse preparation previously
used free downloads; this installation uses local files only, and system network
access was not physically disabled. An inherited `PIP_TARGET` pointing outside
the application was ignored; that target was not created.

Actual receipt: `dependency_environment_ready`; 22 locked distributions matched,
local `pip check` passed, all required imports succeeded. Bootstrap pip 26.2.2
was supplied by the existing interpreter's ensurepip, not downloaded. Source lock
SHA256 `1fb2765bfc9d6aad44bc6be1c1cbb04016b29d8d4b2e557e02a5629b116af595`;
install receipt SHA256 `4013a0278a5b6a32d9585d23960cd5c5f139afad153356781803b3c2459ce614`.

Started that extracted application's local HTTP service with the previously
verified isolated NCNN runtime home. Actual `Fast_Fidelity` / RealeSR-general-v3
inference followed by `luxury_apparel` region protection/reblend/export passed:
331×494 approved diagnostic input → **1324×1976**, revision 2, **588,000 protected
pixels**, **zero mismatches**. Preset request 4.199 s; full workflow 5.766 s,
single run. Separate output files match the hashes in the
[prior current-archive workflow](2026-11-27-current-archive-workflow.md), including
export `53223189fc7621622999282995df9ecf41b87ca973050e67647d59bba1791007`.
The service was stopped after verification. No human/image-quality or held-out
acceptance is inferred; mel014 has known prior calibration exposure.

Private evidence root:
`~/melato-corpus/fidelis/release-evidence/0f5ac9b-offline-installer/` contains
the archives, `preview-receipt.json`, extracted application's
`offline-python-install.{json,log}`, frozen validated lock, installer stdout,
`workflow-receipt.json`, reproduction script and separate `outputs/` PNGs.
The wheelhouse and its per-file hash manifest remain in the earlier
`8d621e2-clean-preview/` collection.

## Validation and remaining gates

Eleven installer regressions and seven release-packaging tests pass; independent
review found no remaining actionable issues. Coverage includes refusal before
mutation, input hashes, inherited environment redirection, incomplete dependency
sets, failed imports, timeouts and retained failure evidence. Actual fresh
installation above exercises the real pip/venv path beyond mocked regressions.
Import/executable lint and diff checks pass. CI includes the installer tests;
archives require installer/module/tests/profile/instructions.

This installs dependencies into a source preview; it does not install Python or
NCNN, redistribute native binaries, provide an SDXL backend, alter model terms,
or change the historical official release manifest. Remaining corpus/source split,
representative quality, blind human review, device and owner release gates remain
open. Continue native runtime/bootstrap packaging and remaining evidence work
without treating those engineering tasks as a broad owner dependency.
