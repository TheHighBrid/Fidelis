"""Catalog, weight, and absolute-process helpers for the RealeSR qualifier."""
from __future__ import annotations

import hashlib
import importlib.util
import os
import shutil
import subprocess  # nosec B404
import sys
from pathlib import Path


def _load_pixels():
    name = 'qualify_realesr_pixels'
    cached = sys.modules.get(name)
    if cached is not None:
        return cached
    path = Path(__file__).resolve().parent / 'qualify_realesr_pixels.py'
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f'Cannot load pixel helpers: {path}')
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_pixels = _load_pixels()
QualificationError = _pixels.QualificationError

MODEL_NAME = 'RealeSR-general-v3'
REPO_ROOT = Path(__file__).resolve().parents[1]
COMMITTED_CATALOG = REPO_ROOT / 'config' / 'photo-candidates.tsv'


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def load_candidate(catalog_path: Path, name: str = MODEL_NAME) -> dict:
    if not catalog_path.is_file():
        raise QualificationError(f'Candidate catalog not found: {catalog_path}')
    for line in catalog_path.read_text(encoding='utf-8').splitlines():
        if not line or line.startswith('#'):
            continue
        parts = line.split('\t')
        if len(parts) < 7 or parts[0] != name:
            continue
        return _candidate_from_parts(parts)
    raise QualificationError(f'Unknown photo candidate: {name}')


def _candidate_from_parts(parts: list[str]) -> dict:
    candidate = {
        'name': parts[0],
        'role': parts[1],
        'revision': parts[2],
        'folder': parts[3],
        'param_sha256': parts[4].strip().lower(),
        'bin_sha256': parts[5].strip().lower(),
        'license_note': parts[6],
    }
    if candidate['role'] != 'mobile-general':
        raise QualificationError(
            f'{MODEL_NAME} role must be mobile-general, found {candidate["role"]}'
        )
    return candidate


def app_home() -> Path:
    return Path(os.environ.get('FIDELIS_HOME', Path.home() / '.local' / 'share' / 'fidelis'))


def active_catalog() -> Path:
    return Path(os.environ.get('FIDELIS_CANDIDATE_CATALOG', COMMITTED_CATALOG))


def model_directory(home: Path) -> Path:
    return home / 'runtime' / f'models-{MODEL_NAME}'


def weight_paths(directory: Path) -> tuple[Path, Path]:
    return directory / 'x4.param', directory / 'x4.bin'


def weights_present(directory: Path) -> bool:
    param_path, bin_path = weight_paths(directory)
    return param_path.is_file() and param_path.stat().st_size > 0 and bin_path.is_file() and bin_path.stat().st_size > 0


def resolve_engine(home: Path) -> Path:
    override = os.environ.get('FIDELIS_ENGINE')
    engine = Path(override) if override else home / 'runtime' / 'realsr-ncnn'
    if not engine.is_file() or not os.access(engine, os.X_OK):
        raise QualificationError(f'Fidelis runtime is not installed: {engine}')
    return engine


def resolve_cli() -> Path:
    override = os.environ.get('FIDELIS_CLI')
    if override:
        return _require_absolute_file(Path(override), 'fidelis CLI path')
    local = REPO_ROOT / 'bin' / 'fidelis'
    if local.is_file():
        return _require_absolute_file(local, 'fidelis CLI path')
    found = shutil.which('fidelis')
    if not found:
        raise QualificationError('fidelis CLI not found')
    return _require_absolute_file(Path(found), 'fidelis CLI path')


def _require_absolute_file(path: Path, label: str) -> Path:
    if not path.is_absolute():
        raise QualificationError(f'refusing relative {label}: {path}')
    resolved = path.resolve()
    if not resolved.is_absolute() or not resolved.is_file():
        raise QualificationError(f'{label} is not an absolute file: {resolved}')
    return resolved


def _installer_path() -> Path:
    raw = os.environ.get('FIDELIS_CANDIDATE_INSTALLER')
    if raw:
        script = Path(raw).resolve()
    else:
        script = (REPO_ROOT / 'scripts' / 'install-photo-candidate.sh').resolve()
        if not script.is_relative_to(REPO_ROOT.resolve()):
            raise QualificationError(f'candidate installer escaped the repository: {script}')
    if not script.is_absolute() or not script.is_file():
        raise QualificationError(f'candidate installer is not an absolute file: {script}')
    return script


# B603 is suppressed on each call below: argv0 is an absolute trusted binary.
def _exec(program: str, args: list[str]) -> subprocess.CompletedProcess[str]:
    tail = [program, *args]
    if Path('/usr/bin/env').is_file():
        return subprocess.run(  # nosec B603
            ['/usr/bin/env', *tail],
            capture_output=True,
            text=True,
            check=False,
        )
    if Path('/bin/env').is_file():
        return subprocess.run(  # nosec B603
            ['/bin/env', *tail],
            capture_output=True,
            text=True,
            check=False,
        )
    if Path('/data/data/com.termux/files/usr/bin/env').is_file():
        return subprocess.run(  # nosec B603
            ['/data/data/com.termux/files/usr/bin/env', *tail],
            capture_output=True,
            text=True,
            check=False,
        )
    raise QualificationError(f'refusing to launch {program} without an absolute env')


def _bash(script: str, args: list[str]) -> subprocess.CompletedProcess[str]:
    tail = [script, *args]
    if Path('/bin/bash').is_file():
        return subprocess.run(  # nosec B603
            ['/bin/bash', *tail],
            capture_output=True,
            text=True,
            check=False,
        )
    if Path('/usr/bin/bash').is_file():
        return subprocess.run(  # nosec B603
            ['/usr/bin/bash', *tail],
            capture_output=True,
            text=True,
            check=False,
        )
    if Path('/data/data/com.termux/files/usr/bin/bash').is_file():
        return subprocess.run(  # nosec B603
            ['/data/data/com.termux/files/usr/bin/bash', *tail],
            capture_output=True,
            text=True,
            check=False,
        )
    raise QualificationError(f'refusing to launch {script} without an absolute bash')


def run_installer() -> None:
    proc = _bash(str(_installer_path()), [MODEL_NAME])
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or '').strip()
        raise QualificationError(f'candidate install failed ({proc.returncode}): {detail}')


def validate_weights(directory: Path, expected: dict) -> tuple[str, str]:
    param_path, bin_path = weight_paths(directory)
    if not weights_present(directory):
        raise QualificationError(f'weights missing: {directory}')
    actual_param = sha256_file(param_path)
    actual_bin = sha256_file(bin_path)
    if actual_param != expected['param_sha256'] or actual_bin != expected['bin_sha256']:
        raise QualificationError(
            'Candidate checksum mismatch: RealeSR-general-v3\n'
            f'  param expected {expected["param_sha256"]}\n'
            f'  param actual   {actual_param}\n'
            f'  bin   expected {expected["bin_sha256"]}\n'
            f'  bin   actual   {actual_bin}'
        )
    return actual_param, actual_bin


def ensure_weights(directory: Path, expected: dict) -> tuple[str, str, bool]:
    invoked = False
    if not weights_present(directory):
        invoked = True
        try:
            run_installer()
        except QualificationError as exc:
            raise QualificationError(f'weights missing: {directory}; {exc}') from exc
    actual_param, actual_bin = validate_weights(directory, expected)
    return actual_param, actual_bin, invoked


def matches_committed_pin(actual_param: str, actual_bin: str, active: dict, committed: dict) -> bool:
    return (
        actual_param == committed['param_sha256']
        and actual_bin == committed['bin_sha256']
        and active['param_sha256'] == committed['param_sha256']
        and active['bin_sha256'] == committed['bin_sha256']
        and active['revision'] == committed['revision']
    )

def _sysctl(name: str) -> str:
    proc = subprocess.run(  # nosec B603
        ['/usr/sbin/sysctl', '-n', name],
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout.strip()


def _darwin_host_details() -> tuple[str | None, int | None]:
    try:
        return _sysctl('machdep.cpu.brand_string'), int(_sysctl('hw.memsize'))
    except (OSError, subprocess.CalledProcessError, ValueError):
        return None, None


def _absolute_git() -> str | None:
    for candidate in ('/usr/bin/git', '/usr/local/bin/git', '/opt/homebrew/bin/git'):
        path = Path(candidate)
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
    found = shutil.which('git')
    if not found:
        return None
    resolved = Path(found).resolve()
    if resolved.is_absolute() and resolved.is_file() and os.access(resolved, os.X_OK):
        return str(resolved)
    return None


def code_sha() -> str | None:
    git = _absolute_git()
    if git is None:
        return None
    try:
        proc = _exec(git, ['-C', str(REPO_ROOT), 'rev-parse', 'HEAD'])
    except (OSError, QualificationError):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or None
