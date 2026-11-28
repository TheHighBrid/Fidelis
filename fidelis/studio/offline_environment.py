"""Install local hash-locked wheels; native runtime and release gates stay separate."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

_PACKAGE = re.compile(r"([A-Za-z0-9][A-Za-z0-9._-]*)==([A-Za-z0-9][A-Za-z0-9.!+_-]*)")
_HASH = re.compile(r"--hash=sha256:([0-9a-fA-F]{64})")
_FILES = ("offline-python-install.log", "offline-python-install.json", "offline-python-validated-lock.txt")
_IMPORTS = ("numpy", "PIL", "scipy", "skimage", "cv2", "yaml", "httpx", "pytest")


def _name(value):
    return re.sub(r"[-_.]+", "-", value).lower()


def _sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_lock(path):
    raw = path.read_bytes()
    entries = {}
    for line in raw.decode("utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        tokens = line.split()
        package = _PACKAGE.fullmatch(tokens[0])
        hashes = [_HASH.fullmatch(token) for token in tokens[1:]]
        if package is None or not hashes or not all(hashes):
            raise ValueError("Lock entries must be exact package==version and SHA256 hashes only")
        name, version = package.groups()
        normalized = _name(name)
        if normalized in entries:
            raise ValueError("Duplicate locked distribution: " + name)
        entries[normalized] = {"version": version, "hashes": sorted({m[1].lower() for m in hashes})}
    if not entries:
        raise ValueError("Requirements lock is empty")
    canonical = "\n".join(name + "==" + value["version"] + " " + " ".join(
        "--hash=sha256:" + digest for digest in value["hashes"]
    ) for name, value in sorted(entries.items())) + "\n"
    return entries, canonical, hashlib.sha256(raw).hexdigest()


def _validate_wheels(directory, entries):
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("Wheelhouse must be a real local directory")
    verified, found = [], set()
    for path in sorted(directory.iterdir()):
        parts = path.stem.split("-")
        if (path.suffix != ".whl" or path.is_symlink() or not path.is_file()
                or len(parts) not in (5, 6)):
            raise ValueError("Invalid or unsafe wheel: " + path.name)
        name, version = _name(parts[0]), parts[1]
        if name not in entries or version != entries[name]["version"]:
            raise ValueError("Unexpected wheel distribution/version: " + path.name)
        digest = _sha(path)
        if digest not in entries[name]["hashes"]:
            raise ValueError("Wheel hash mismatch: " + path.name)
        found.add(name)
        verified.append({"file": path.name, "sha256": digest, "bytes": path.stat().st_size})
    if found != set(entries):
        raise ValueError("Missing locked wheels: " + ", ".join(sorted(set(entries) - found)))
    return verified


def _check_target(root):
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Application root must be an existing real directory")
    for path in [root / ".venv", *(root / name for name in _FILES)]:
        if path.exists() or path.is_symlink():
            raise FileExistsError("Refusing existing environment or installation evidence: " + str(path))


def _environment():
    env = {key: value for key, value in os.environ.items()
           if not key.startswith("PIP_") and key not in ("PYTHONHOME", "PYTHONPATH")}
    env.update(PIP_CONFIG_FILE=os.devnull, PIP_DISABLE_PIP_VERSION_CHECK="1",
               PIP_NO_INPUT="1", PYTHONNOUSERSITE="1")
    return env


def _run(command, root, env, log):
    log.write(json.dumps({"command": list(map(str, command))}) + "\n")
    log.flush()
    try:
        result = subprocess.run(list(map(str, command)), cwd=root, env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, check=False, timeout=300)
    except subprocess.SubprocessError as error:
        raise RuntimeError("Offline install subprocess failed; see installation log") from error
    log.write(result.stdout)
    log.flush()
    if result.returncode:
        raise RuntimeError(f"Offline install command failed ({result.returncode}); see installation log")
    return result.stdout


def _verify(python, root, env, log, entries):
    script = (
        "import importlib,importlib.metadata,json,platform,sys; "
        f"[importlib.import_module(name) for name in {_IMPORTS!r}]; "
        "print(json.dumps({'python_executable':sys.executable,'python_version':platform.python_version(),"
        "'platform':platform.platform(),'installed_versions':"
        "{d.metadata['Name']:d.version for d in importlib.metadata.distributions()}}))"
    )
    result = json.loads(_run([python, "-I", "-c", script], root, env, log))
    installed = {_name(name): version for name, version in result["installed_versions"].items()}
    if any(installed.get(name) != value["version"] for name, value in entries.items()):
        raise RuntimeError("Installed dependency versions do not match the validated lock")
    return result


def _install(root, wheelhouse, snapshot, python_executable, entries, log):
    env = _environment()
    # Reserve the environment path exclusively, so a race cannot overwrite one
    # created since preflight. venv receives only the empty directory we own.
    (root / ".venv").mkdir()
    _run([python_executable, "-I", "-m", "venv", root / ".venv"], root, env, log)
    python = root / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    command = [python, "-I", "-m", "pip", "--disable-pip-version-check", "install",
               "--no-index", "--require-hashes", "--only-binary=:all:", "--no-cache-dir",
               "--find-links", wheelhouse, "-r", snapshot]
    _run(command, root, env, log)
    return _verify(python, root, env, log, entries)


def install_offline_environment(app_root, *, wheelhouse, requirements_lock, python_executable):
    """Create a new dependency environment without network indexes or overwrite.

    The interpreter and its stdlib venv/ensurepip must already be installed.
    Failures retain their environment/log/receipt. No runtime/model installation
    or release readiness is certified by a successful dependency import check.
    """
    root, wheels, lock = map(lambda value: Path(value).absolute(),
                            (app_root, wheelhouse, requirements_lock))
    _check_target(root)
    entries, canonical, lock_sha = _read_lock(lock)
    verified = _validate_wheels(wheels, entries)
    receipt = {"schema_version": 1, "status": "failed", "requirements_lock_sha256": lock_sha,
               "validated_lock_sha256": hashlib.sha256(canonical.encode()).hexdigest(),
               "wheels": verified, "python_requested": str(python_executable),
               "native_runtime_readiness": "unverified", "model_readiness": "unverified",
               "release_approval": "not_granted", "network_indexes_enabled": False,
               "scope": "Local dependency installation and imports only; not fresh-machine bootstrap"}
    snapshot = root / _FILES[2]
    # Exclusive creation ensures a concurrent attempt cannot overwrite evidence.
    with (root / _FILES[0]).open("x", encoding="utf-8") as log:
        try:
            with snapshot.open("x", encoding="utf-8") as stream:
                stream.write(canonical)
            receipt.update(_install(root, wheels, snapshot, python_executable, entries, log))
            receipt["status"] = "dependency_environment_ready"
        except Exception as error:
            receipt["error"] = str(error)
            raise
        finally:
            with (root / _FILES[1]).open("x", encoding="utf-8") as stream:
                json.dump(receipt, stream, indent=2)
                stream.write("\n")
    return receipt
