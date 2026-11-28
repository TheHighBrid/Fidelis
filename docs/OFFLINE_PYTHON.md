# Install preview Python dependencies from local wheels

This step creates a new `.venv` in an extracted Fidelis source preview. It does
not install Python, NCNN, models, PyTorch or ComfyUI and does not certify a release.
Use an existing compatible interpreter with the standard `venv`/`ensurepip`
modules. Existing environments and earlier install receipts are refused rather
than overwritten. Keep the log and receipt when diagnosing a failed attempt.

The supplied profile `config/offline/macos-arm64-py312-20261128.txt` records the
22 exact wheel hashes used by the Apple M1 preview check. It was exercised with
CPython 3.12.16 on macOS 27.3 arm64. Its native wheels require their recorded
platform tags; this is not a universal macOS, Linux or Windows lock file. Choose
a separately verified target profile for other systems. Test-only dependencies
are retained in this engineering preview profile; it is not the final production
dependency policy.

On a compatible preparation machine with package downloads available:

```bash
python3.12 -m pip download --only-binary=:all: --require-hashes \
  --dest /path/to/wheelhouse \
  -r config/offline/macos-arm64-py312-20261128.txt
```

Transfer the audited source preview and the complete wheelhouse to the target.
From a **new extraction**, before creating `.venv`, run:

```bash
python3.12 scripts/install-offline-python.py \
  --wheelhouse /path/to/wheelhouse \
  --requirements-lock config/offline/macos-arm64-py312-20261128.txt
```

The installer checks pinned requirement syntax and local wheel hashes before
creating the environment. It invokes pip with no index, no cache, wheel-only
packages and required hashes, then checks the scientific/Studio imports. It
writes `offline-python-install.json` and `offline-python-install.log` in the
extraction. `dependency_environment_ready` refers only to that environment;
runtime/model and release readiness remain unverified. No network fallback or
automatic replacement of an existing environment occurs. The machine's network
is not disabled by this command.

After independently staging or installing the verified local NCNN runtime and
the cleared model, bind the application explicitly to loopback:

```bash
export FIDELIS_HOME=/path/to/verified-local-runtime-home
.venv/bin/python scripts/web-ui.py --bind 127.0.0.1 --port 8765
```

The source preview takes aligned base/texture passes for region editing. Follow
the [onboarding workflow](../ONBOARDING.md) and [packaging limits](RELEASE_PACKAGING.md).
The historical `install-offline.sh` in a model bundle stages CLI/model files;
it does not by itself provide Python dependencies or a native inference engine.
Keep those installation steps separate when assessing a complete deployment.
