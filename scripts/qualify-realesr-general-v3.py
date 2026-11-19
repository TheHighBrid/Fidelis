#!/usr/bin/env python3
"""Qualify the pinned RealeSR-general-v3 zero-cost texture workflow.

The workflow installs or validates the catalogued NCNN weights, runs the local
realsr-ncnn engine at its fixed 4x scale, copies fully locked pixels from the
precision base, and checks that export with scripts/verify-protected-export.py.
A passing receipt is E1 for a fixture or non-pinned run. E2 is recorded only
when --record-live is set and the installed bytes match the committed catalog
pin. E3 and E4 are never written: visual review and release are separate
evidence. M1 8GB and Android markers are host reports, not acceptance.

No grain, sharpening, beauty smoothing, cloud fallback, or paid API is applied.
One PNG is published. An output whose size is not the expected scale is deleted
and the run stops; this script does not resize it.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import time

import numpy as np
from PIL import Image


MODEL_NAME = 'RealeSR-general-v3'
SCALE = 4
SCHEMA_VERSION = 1
REPO_ROOT = Path(__file__).resolve().parents[1]
COMMITTED_CATALOG = REPO_ROOT / 'config' / 'photo-candidates.tsv'
VERIFIER = Path(__file__).resolve().parent / 'verify-protected-export.py'
M1_8GB_BYTES = 8 * 1024 ** 3


class QualificationError(Exception):
    def __init__(self, message: str, code: int = 1):
        super().__init__(message)
        self.code = code


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
    raise QualificationError(f'Unknown photo candidate: {name}')


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


def resolve_cli() -> str:
    override = os.environ.get('FIDELIS_CLI')
    if override:
        return override
    local = REPO_ROOT / 'bin' / 'fidelis'
    if local.is_file():
        return str(local)
    return 'fidelis'


def command_prefix(executable: str) -> list[str]:
    path = Path(executable)
    if path.is_file() and not os.access(path, os.X_OK):
        return ['bash', executable]
    return [executable]


def run_installer() -> None:
    installer = os.environ.get(
        'FIDELIS_CANDIDATE_INSTALLER',
        str(REPO_ROOT / 'scripts' / 'install-photo-candidate.sh'),
    )
    proc = subprocess.run(
        ['bash', installer, MODEL_NAME],
        capture_output=True,
        text=True,
        check=False,
    )
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


def load_rgb_png(path: Path) -> np.ndarray:
    try:
        with Image.open(path) as image:
            if image.format != 'PNG':
                raise QualificationError(f'{path} must be a PNG file')
            if image.mode != 'RGB':
                raise QualificationError(f'{path} must be untagged 8-bit RGB')
            if image.info.get('icc_profile'):
                raise QualificationError(f'{path} carries an ICC profile outside this workflow contract')
            orientation = image.getexif().get(274)
            if orientation not in (None, 1):
                raise QualificationError(f'{path} has an EXIF orientation outside this workflow contract')
            pixels = np.array(image, copy=True)
    except QualificationError:
        raise
    except (OSError, ValueError) as exc:
        raise QualificationError(f'{path} could not be read: {exc}') from exc
    if pixels.dtype != np.uint8 or pixels.ndim != 3 or pixels.shape[2] != 3:
        raise QualificationError(f'{path} must be 8-bit RGB')
    if pixels.shape[0] == 0 or pixels.shape[1] == 0:
        raise QualificationError(f'{path} has no pixels')
    return pixels


def save_rgb_png(path: Path, pixels: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(pixels, mode='RGB').save(path, format='PNG')


def expected_size(width: int, height: int) -> tuple[int, int]:
    return width * SCALE, height * SCALE


def require_expected_scale(
    actual_width: int,
    actual_height: int,
    expected_width: int,
    expected_height: int,
    subject: str = 'output',
) -> None:
    if actual_width != expected_width or actual_height != expected_height:
        raise QualificationError(
            f'{subject} dimensions {actual_width}x{actual_height} do not match expected '
            f'scale {SCALE} ({expected_width}x{expected_height}); refusing to resize'
        )


def validate_protect_mask(mask: np.ndarray) -> None:
    if mask.ndim != 2 or not np.issubdtype(mask.dtype, np.number):
        raise QualificationError('protect mask must be a numeric HxW array')
    if not np.all(np.isfinite(mask)) or np.any((mask < 0) | (mask > 1)):
        raise QualificationError('protect mask values must be finite within [0, 1]')


def load_protect_mask(path: Path) -> np.ndarray:
    try:
        with np.load(path, allow_pickle=False) as data:
            if 'protect' not in data.files:
                raise QualificationError('NPZ requires a protect mask')
            mask = np.array(data['protect'])
    except QualificationError:
        raise
    except (OSError, ValueError, KeyError) as exc:
        raise QualificationError(f'protect mask could not be read: {exc}') from exc
    validate_protect_mask(mask)
    return mask


def align_protect_mask(mask: np.ndarray, input_shape: tuple[int, int], output_shape: tuple[int, int]) -> np.ndarray:
    """Accept an input-sized or output-sized mask.

    An input-sized mask is repeated as exact scale-by-scale blocks. Any other
    shape stops the run. The mask is not interpolated onto the output.
    """
    if mask.shape == output_shape:
        return mask
    if mask.shape == input_shape:
        return np.repeat(np.repeat(mask, SCALE, axis=0), SCALE, axis=1)
    in_h, in_w = input_shape
    out_h, out_w = output_shape
    raise QualificationError(
        f'protect mask shape {mask.shape[1]}x{mask.shape[0]} matches neither the input '
        f'{in_w}x{in_h} nor the expected output {out_w}x{out_h}; refusing to resize'
    )


def integer_replicate_rgb(image: np.ndarray) -> np.ndarray:
    if image.ndim != 3 or image.shape[2] != 3 or image.dtype != np.uint8:
        raise QualificationError('precision source must be uint8 RGB')
    return np.repeat(np.repeat(image, SCALE, axis=0), SCALE, axis=1)


def composite_protected(base: np.ndarray, texture: np.ndarray, mask: np.ndarray) -> np.ndarray:
    if base.shape != texture.shape or base.dtype != np.uint8 or texture.dtype != np.uint8:
        raise QualificationError('texture and base must be uint8 RGB arrays of equal shape')
    if mask.shape != base.shape[:2]:
        raise QualificationError('protect mask dimensions differ from base')
    validate_protect_mask(mask)
    export = np.array(texture, copy=True)
    export[mask == 1] = base[mask == 1]
    return export


def prepare_base(source: np.ndarray, base_path: Path | None, expected: tuple[int, int]) -> np.ndarray:
    if base_path is None:
        return integer_replicate_rgb(source)
    base = load_rgb_png(base_path)
    require_expected_scale(base.shape[1], base.shape[0], expected[0], expected[1], subject='base')
    return base


def _darwin_host_details() -> tuple[str | None, int | None]:
    try:
        brand = subprocess.run(
            ['sysctl', '-n', 'machdep.cpu.brand_string'],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        mem_text = subprocess.run(
            ['sysctl', '-n', 'hw.memsize'],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        return brand, int(mem_text)
    except (OSError, subprocess.CalledProcessError, ValueError):
        return None, None


def host_report() -> dict:
    system = platform.system()
    machine = platform.machine()
    report = {
        'system': system,
        'machine': machine,
        'kernel': platform.release(),
        'target_m1_8gb': 'not_run',
        'target_android': 'not_run',
    }
    prefix = os.environ.get('PREFIX', '')
    if 'com.termux' in prefix or os.environ.get('ANDROID_ROOT') or os.environ.get('ANDROID_DATA'):
        report['target_android'] = 'host_reports_android_markers'
    if system == 'Darwin' and machine in {'arm64', 'aarch64'}:
        brand, mem_bytes = _darwin_host_details()
        if brand is not None:
            report['darwin_cpu'] = brand
        if mem_bytes is not None:
            report['darwin_mem_bytes'] = mem_bytes
        if brand == 'Apple M1' and mem_bytes == M1_8GB_BYTES:
            report['target_m1_8gb'] = 'host_reports_m1_8gb'
    return report


def code_sha() -> str | None:
    try:
        proc = subprocess.run(
            ['git', '-C', str(REPO_ROOT), 'rev-parse', 'HEAD'],
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    value = proc.stdout.strip()
    return value or None


def select_evidence_level(
    *,
    record_live: bool,
    weights_match_committed_pin: bool,
    engine_executed: bool,
    dimensions_match: bool,
    protection_pass: bool,
) -> str:
    if not (engine_executed and dimensions_match and protection_pass):
        raise QualificationError('passing receipt requires a completed dimension and protection check')
    if record_live and weights_match_committed_pin:
        return 'E2'
    return 'E1'


def assert_receipt_honest(receipt: dict) -> None:
    level = receipt.get('evidence_level')
    if level not in {'E1', 'E2'}:
        raise QualificationError(f'receipt refused evidence level {level}')
    if receipt.get('e3_visual_device') != 'not_run' or receipt.get('e4_released') != 'not_run':
        raise QualificationError('receipt refused visual or release acceptance')
    hardware = receipt.get('hardware') or {}
    if hardware.get('target_m1_8gb') == 'accepted' or hardware.get('target_android') == 'accepted':
        raise QualificationError('receipt refused device acceptance')
    if level == 'E2':
        if receipt.get('live_inference') is not True:
            raise QualificationError('receipt refused evidence level E2 without a real run')
        model = receipt.get('model') or {}
        output = receipt.get('output') or {}
        protection = receipt.get('protection') or {}
        if model.get('matches_committed_pin') is not True:
            raise QualificationError('receipt refused evidence level E2 without the committed pin')
        if output.get('dimensions_match_scale') is not True:
            raise QualificationError('receipt refused evidence level E2 with a dimension mismatch')
        if protection.get('pass') is not True or protection.get('changed_protected_pixels') != 0:
            raise QualificationError('receipt refused evidence level E2 without protection verification')


def build_receipt(
    *,
    record_live: bool,
    weights_match_committed_pin: bool,
    engine_executed: bool,
    dimensions_match: bool,
    protection: dict,
    hardware: dict,
    model: dict,
    engine: dict,
    source: dict,
    output: dict,
    elapsed_ms: int,
    installer_invoked: bool,
    base_mode: str,
) -> dict:
    level = select_evidence_level(
        record_live=record_live,
        weights_match_committed_pin=weights_match_committed_pin,
        engine_executed=engine_executed,
        dimensions_match=dimensions_match,
        protection_pass=bool(protection.get('pass')) and protection.get('changed_protected_pixels') == 0,
    )
    live = level == 'E2'
    receipt = {
        'schema_version': SCHEMA_VERSION,
        'task': 'F06',
        'linear': 'MEL-60',
        'command': 'qualify-realesr-general-v3',
        'created_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'pass': True,
        'evidence_level': level,
        'live_inference': live,
        'e3_visual_device': 'not_run',
        'e4_released': 'not_run',
        'code_sha': code_sha(),
        'hardware': hardware,
        'model': model,
        'engine': engine,
        'input': source,
        'output': output,
        'protection': protection,
        'base_mode': base_mode,
        'installer_invoked': installer_invoked,
        'runtime': {'wall_elapsed_ms': elapsed_ms},
        'postprocess': 'none',
        'cloud_fallback': False,
        'paid_service': False,
        'api_fee': 0,
        'output_image_count': 1,
        'limitations': [
            'Fully locked pixels (protect == 1) are copied from the precision base.',
            'Partial and unlocked pixels keep the engine output.',
            'No grain, sharpening, or beauty smoothing is applied.',
            'E2 records live inference of the committed pin on the reported host.',
            'M1 8GB and Android visual acceptance remain not_run in this receipt.',
            'API fee is zero and no cloud fallback is invoked.',
        ],
    }
    assert_receipt_honest(receipt)
    return receipt


def write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.new')
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    os.replace(temporary, path)


def invalidate(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.exists():
        raise QualificationError(f'output path is not a file: {path}')


def run_upscale(cli: str, source: Path, destination: Path) -> int:
    command = command_prefix(cli) + ['upscale', str(source), str(destination), '--model', MODEL_NAME]
    started = time.perf_counter()
    proc = subprocess.run(command, capture_output=True, text=True, check=False)
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or '').strip()
        raise QualificationError(f'upscale failed ({proc.returncode}): {detail}')
    if not destination.is_file() or destination.stat().st_size == 0:
        raise QualificationError('upscale produced no output')
    return elapsed_ms


def verify_export(base_png: Path, export_png: Path, mask_npz: Path) -> dict:
    proc = subprocess.run(
        [sys.executable, str(VERIFIER), str(base_png), str(export_png), str(mask_npz)],
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        result = json.loads(proc.stdout or '{}')
    except json.JSONDecodeError as exc:
        raise QualificationError(f'protected export verifier returned invalid JSON: {proc.stdout!r}') from exc
    if proc.returncode != 0 or result.get('pass') is not True or result.get('changed_protected_pixels') != 0:
        detail = (proc.stdout or proc.stderr or '').strip()
        raise QualificationError(f'protected export verification failed: {detail}')
    return result


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('masks', type=Path, help='NPZ with a protect array; 1.0 is fully locked')
    parser.add_argument('--base', type=Path, help='RGB PNG precision base already at input width*4 by height*4')
    parser.add_argument('--receipt', type=Path, help='Receipt JSON path (default: OUTPUT.receipt.json)')
    parser.add_argument(
        '--record-live',
        action='store_true',
        help='Record E2 when this process ran the local engine on the committed weight pin. Never records E3 or E4.',
    )
    args = parser.parse_args(argv)
    receipt_path = args.receipt or args.output.with_suffix('.receipt.json')
    invalidate(args.output)
    invalidate(receipt_path)

    if not args.input.is_file():
        raise QualificationError(f'Input not found: {args.input}')
    if not args.masks.is_file():
        raise QualificationError(f'Protect mask not found: {args.masks}')

    committed = load_candidate(COMMITTED_CATALOG)
    active = load_candidate(active_catalog())
    home = app_home()
    engine = resolve_engine(home)
    directory = model_directory(home)
    actual_param, actual_bin, installer_invoked = ensure_weights(directory, active)
    pinned = matches_committed_pin(actual_param, actual_bin, active, committed)

    source = load_rgb_png(args.input)
    input_height, input_width = source.shape[:2]
    expected_width, expected_height = expected_size(input_width, input_height)
    mask = align_protect_mask(load_protect_mask(args.masks), source.shape[:2], (expected_height, expected_width))
    base = prepare_base(source, args.base, (expected_width, expected_height))
    require_expected_scale(base.shape[1], base.shape[0], expected_width, expected_height)

    with tempfile.TemporaryDirectory(prefix='fidelis-f06-') as temporary:
        temp = Path(temporary)
        raw_path = temp / 'texture.png'
        elapsed_ms = run_upscale(resolve_cli(), args.input, raw_path)
        texture = load_rgb_png(raw_path)
        require_expected_scale(texture.shape[1], texture.shape[0], expected_width, expected_height)
        export = composite_protected(base, texture, mask)
        staged = temp / 'export.png'
        base_png = temp / 'base.png'
        mask_npz = temp / 'protect.npz'
        save_rgb_png(staged, export)
        save_rgb_png(base_png, base)
        np.savez(mask_npz, protect=mask)
        protection = verify_export(base_png, staged, mask_npz)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staged, args.output)

    if args.record_live and not pinned:
        print(
            'record-live was set, but the installed weights are not the committed '
            'RealeSR-general-v3 pin; receipt stays at E1.',
            file=sys.stderr,
        )

    receipt = build_receipt(
        record_live=args.record_live,
        weights_match_committed_pin=pinned,
        engine_executed=True,
        dimensions_match=True,
        protection=protection,
        hardware=host_report(),
        model={
            'name': MODEL_NAME,
            'role': active['role'],
            'revision': active['revision'],
            'committed_revision': committed['revision'],
            'license_note': active['license_note'],
            'committed_license_note': committed['license_note'],
            'param_sha256': actual_param,
            'bin_sha256': actual_bin,
            'matches_committed_pin': pinned,
        },
        engine={
            'name': 'realsr-ncnn',
            'path': str(engine),
            'sha256': sha256_file(engine),
            'scale': SCALE,
        },
        source={
            'path': str(args.input),
            'width': input_width,
            'height': input_height,
            'sha256': sha256_file(args.input),
        },
        output={
            'path': str(args.output),
            'width': expected_width,
            'height': expected_height,
            'expected_width': expected_width,
            'expected_height': expected_height,
            'sha256': sha256_file(args.output),
            'dimensions_match_scale': True,
        },
        elapsed_ms=elapsed_ms,
        installer_invoked=installer_invoked,
        base_mode='supplied-base' if args.base else 'integer-replicated-source',
    )
    write_json_atomic(receipt_path, receipt)
    print(f'Qualification receipt: {receipt_path}')
    print(f'Evidence level: {receipt["evidence_level"]}')
    return 0


def main(argv: list[str] | None = None) -> int:
    try:
        return run(argv)
    except QualificationError as exc:
        print(exc, file=sys.stderr)
        return exc.code


if __name__ == '__main__':
    raise SystemExit(main())
