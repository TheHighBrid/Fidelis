"""Byte-verified macOS preview bootstrap; no downloads or quality certification."""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import platform
import re
import shutil
import stat
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

from fidelis.studio.offline_models import stage_models

_RUNTIMES = {
    "realsr-ncnn-vulkan-20220728": "realsr-binary",
    "realesrgan-ncnn-vulkan-20220424": "realesrgan-binary",
}
_MODEL = "RealeSR-general-v3"
_MODEL_FOLDER = "models-RealeSR-general-v3"


def _sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _digest(value, label):
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError("Missing or invalid pinned SHA256: " + label)
    return value


def _relative(value):
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValueError("Expected a confined relative path")
    path = PurePosixPath(value)
    if (path.is_absolute() or not path.parts or path.as_posix() != value
            or any(part in ("..", ".") for part in path.parts)):
        raise ValueError("Unsafe relative path: " + value)
    return path


def _repo_file(root, relative):
    path = root.joinpath(*_relative(relative).parts)
    if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("Missing or unsafe repository file: " + relative)
    return path


def _catalog(root):
    path = _repo_file(root, "config/model-provenance-v1.json")
    catalog = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(catalog, dict) or catalog.get("schema_version") != 1:
        raise ValueError("Unsupported native preview catalog")
    runtimes = catalog.get("runtimes", [])
    if (not isinstance(runtimes, list) or len(runtimes) != len(_RUNTIMES)
            or {item.get("runtime_id") for item in runtimes if isinstance(item, dict)} != set(_RUNTIMES)):
        raise ValueError("Preview requires exactly the two supported pinned native runtimes")
    records = catalog.get("models", [])
    if not isinstance(records, list) or any(not isinstance(model, dict) for model in records):
        raise ValueError("Invalid model catalog")
    models = [model for model in records if model.get("model_id") == _MODEL]
    if (len(models) != 1 or models[0].get("terms", {}).get("production_terms_cleared") is not True
            or models[0].get("local_relative_dir") != "runtime/" + _MODEL_FOLDER
            or set(models[0].get("weights", {})) != {"x4.param", "x4.bin"}):
        raise ValueError("The exact RealeSR model must have cleared terms and pinned native weights")
    for name, digest in models[0]["weights"].items():
        _digest(digest, name)
    return catalog, models[0], _sha(path)


def _archive_path(directory, runtime):
    url = urlsplit(runtime.get("download_url", ""))
    name = PurePosixPath(url.path).name
    if url.scheme != "https" or not url.netloc or url.query or url.fragment or not name.endswith(".zip"):
        raise ValueError("Runtime needs a pinned HTTPS ZIP release URL")
    path = directory / name
    if path.is_symlink() or not path.is_file() or path.resolve().parent != directory.resolve():
        raise ValueError("Missing or unsafe local runtime archive: " + name)
    expected = _digest(runtime.get("archive_sha256"), name)
    if _sha(path) != expected:
        raise ValueError("Runtime archive checksum mismatch: " + name)
    return path


def _binary(archive_path, member, target, expected):
    _relative(member)
    _digest(expected, "native binary")
    with zipfile.ZipFile(archive_path) as archive:
        matches = [info for info in archive.infolist() if info.filename == member]
        if (len(matches) != 1 or matches[0].is_dir()
                or stat.S_IFMT(matches[0].external_attr >> 16) == stat.S_IFLNK):
            raise ValueError("Selected ZIP member must be one unique regular binary")
        with archive.open(matches[0]) as source, target.open("xb") as output:
            shutil.copyfileobj(source, output, length=1024 * 1024)
    if _sha(target) != expected:
        raise ValueError("Native binary checksum mismatch")
    target.chmod(0o755)


def _runtime(root, archive_dir, runtime_dir, item):
    identity = item["runtime_id"]
    if item.get("commercial_status") != "cleared_permissive":
        raise ValueError("Runtime terms are not cleared: " + identity)
    archive = _archive_path(archive_dir, item)
    notice = _repo_file(root, item.get("license_notice_path"))
    expected_notice = _digest(item.get("license_notice_sha256"), identity + " notice")
    if _sha(notice) != expected_notice:
        raise ValueError("Runtime license notice checksum mismatch: " + identity)
    destination = runtime_dir / _RUNTIMES[identity]
    _binary(archive, item.get("archive_member"), destination, item.get("macos_binary_sha256"))
    notice_target = runtime_dir / "NOTICES" / (identity + ".txt")
    shutil.copyfile(notice, notice_target)
    if _sha(notice_target) != expected_notice:
        raise ValueError("Staged runtime license notice checksum mismatch")
    archive_digest = _sha(archive)
    if archive_digest != item["archive_sha256"]:
        raise ValueError("Runtime archive changed during staging")
    return {"runtime_id": identity, "archive": archive.name, "archive_sha256": archive_digest,
            "archive_member": item["archive_member"], "binary_path": "runtime/" + destination.name,
            "binary_sha256": _sha(destination), "license": item.get("license"),
            "license_notice_path": "runtime/NOTICES/" + notice_target.name,
            "license_notice_sha256": expected_notice}


def _model(root, cache, runtime, model):
    receipt = stage_models(root, cache, runtime)
    if [entry["model_id"] for entry in receipt["included"]] != [_MODEL]:
        raise ValueError("Preview must stage exactly the cleared RealeSR-general-v3 model")
    folder = runtime / _MODEL_FOLDER
    for name, expected in model["weights"].items():
        if _sha(folder / name) != expected:
            raise ValueError("Staged model checksum mismatch: " + name)
    registration = {"schema_version": 1, "name": _MODEL, "engine": "realsr-ncnn",
                    "format": "ncnn", "scale": 4, "source": model["source"],
                    "sha256": {"param": model["weights"]["x4.param"], "bin": model["weights"]["x4.bin"]},
                    "candidate": {"role": model.get("role"), "license_note": model["terms"]["license"]}}
    (folder / "fidelis-model.json").write_text(json.dumps(registration, indent=2) + "\n")
    receipt["included"][0]["license_notice_sha256"] = _sha(folder / "LICENSE.txt")
    return receipt


def _rename_exclusive(staging, target):
    """Darwin RENAME_EXCL never replaces even a concurrently created empty home."""
    library = ctypes.CDLL(None, use_errno=True)
    try:
        rename = library.renamex_np
    except AttributeError as error:
        raise RuntimeError("Exclusive macOS directory publication is unavailable") from error
    rename.argtypes = (ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint)
    rename.restype = ctypes.c_int
    if rename(os.fsencode(staging), os.fsencode(target), 0x00000004) != 0:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code), str(target))


def _stage(root, archives, cache, home, catalog, model, catalog_sha):
    runtime = home / "runtime"
    (runtime / "NOTICES").mkdir(parents=True)
    runtimes = [_runtime(root, archives, runtime, item) for item in catalog["runtimes"]]
    models = _model(root, cache, runtime, model)
    wrapper = _repo_file(root, "scripts/ncnn-preview-runtime.sh")
    wrapper_digest = _sha(wrapper)
    shutil.copyfile(wrapper, runtime / "realsr-ncnn")
    if _sha(runtime / "realsr-ncnn") != wrapper_digest:
        raise ValueError("Staged runtime wrapper checksum mismatch")
    (runtime / "realsr-ncnn").chmod(0o755)
    receipt = {"schema_version": 1, "os": "Darwin", "architecture": "arm64",
               "engine": "realsr-ncnn-vulkan-20220728", "catalog_sha256": catalog_sha,
               "scope": "byte_verified_not_quality_or_release", "native_execution_verified": False,
               "release_approval": "not_granted", "runtimes": runtimes, "models": models,
               "wrapper": {"path": "runtime/realsr-ncnn", "sha256": _sha(runtime / "realsr-ncnn")}}
    for filename in ("install.json", "native-preview-receipt.json"):
        (home / filename).write_text(json.dumps(receipt, indent=2) + "\n")
    return receipt


def bootstrap_native_preview(repo_root, *, archive_dir, model_cache, app_home) -> dict:
    """Publish a new isolated local native home after byte/license verification.

    This macOS arm64 helper does not download, execute native code, install Python,
    amend the official release candidate, or overwrite an existing installation.
    """
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        raise ValueError("Native preview bootstrap supports macOS arm64 only")
    root, archives, cache, target = map(lambda value: Path(value).absolute(),
                                      (repo_root, archive_dir, model_cache, app_home))
    if target.exists() or target.is_symlink():
        raise FileExistsError("Refusing existing app home: " + str(target))
    if archives.is_symlink() or not archives.is_dir() or cache.is_symlink() or not cache.is_dir():
        raise ValueError("Archive and model cache inputs must be real local directories")
    catalog, model, catalog_sha = _catalog(root)
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix="." + target.name + ".staging-", dir=target.parent))
    try:
        receipt = _stage(root, archives, cache, staging, catalog, model, catalog_sha)
        _rename_exclusive(staging, target)
        return receipt
    finally:
        if staging.exists():
            shutil.rmtree(staging)
