"""Receipt and pipeline helpers for qualify-realesr-general-v3.

The CLI entry point remains scripts/qualify-realesr-general-v3.py. Receipt
fields, evidence levels, and protect == 1 compositing stay the same.
"""
from __future__ import annotations

import importlib.util
import json
import os
import platform
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict

import numpy as np


def _load_named(filename: str, module_name: str):
    cached = sys.modules.get(module_name)
    if cached is not None:
        return cached
    path = Path(__file__).resolve().parent / filename
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f'Cannot load {path}')
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


_pixels = _load_named('qualify_realesr_pixels.py', 'qualify_realesr_pixels')
_runtime = _load_named('qualify_realesr_runtime.py', 'qualify_realesr_runtime')

QualificationError = _pixels.QualificationError
SCALE = _pixels.SCALE
align_protect_mask = _pixels.align_protect_mask
composite_protected = _pixels.composite_protected
expected_size = _pixels.expected_size
load_protect_mask = _pixels.load_protect_mask
load_rgb_png = _pixels.load_rgb_png
prepare_base = _pixels.prepare_base
require_expected_scale = _pixels.require_expected_scale
save_rgb_png = _pixels.save_rgb_png

MODEL_NAME = _runtime.MODEL_NAME
REPO_ROOT = _runtime.REPO_ROOT
COMMITTED_CATALOG = _runtime.COMMITTED_CATALOG
sha256_file = _runtime.sha256_file
load_candidate = _runtime.load_candidate
app_home = _runtime.app_home
active_catalog = _runtime.active_catalog
model_directory = _runtime.model_directory
resolve_engine = _runtime.resolve_engine
resolve_cli = _runtime.resolve_cli
ensure_weights = _runtime.ensure_weights
matches_committed_pin = _runtime.matches_committed_pin
_require_absolute_file = _runtime._require_absolute_file
_exec = _runtime._exec
_bash = _runtime._bash
_darwin_host_details = _runtime._darwin_host_details
code_sha = _runtime.code_sha

SCHEMA_VERSION = 1
VERIFIER = Path(__file__).resolve().parent / 'verify-protected-export.py'
M1_8GB_BYTES = 8 * 1024 ** 3
UNPINNED_LIVE_NOTE = (
    'record-live was set, but the installed weights are not the committed '
    'RealeSR-general-v3 pin; receipt stays at E1.'
)


class ReceiptInputs(TypedDict):
    record_live: bool
    weights_match_committed_pin: bool
    engine_executed: bool
    dimensions_match: bool
    protection: dict
    hardware: dict
    model: dict
    engine: dict
    source: dict
    output: dict
    elapsed_ms: int
    installer_invoked: bool
    base_mode: str


@dataclass(frozen=True)
class ModelState:
    committed: dict
    active: dict
    engine: Path
    actual_param: str
    actual_bin: str
    installer_invoked: bool
    pinned: bool


@dataclass(frozen=True)
class PixelState:
    source: np.ndarray
    input_width: int
    input_height: int
    expected_width: int
    expected_height: int
    mask: np.ndarray
    base: np.ndarray


@dataclass(frozen=True)
class PreparedRun:
    input_path: Path
    output_path: Path
    base_path: Path | None
    record_live: bool
    model: ModelState
    pixels: PixelState


@dataclass(frozen=True)
class PipelineResult:
    elapsed_ms: int
    protection: dict


def _host_targets() -> dict:
    return {
        'system': platform.system(),
        'machine': platform.machine(),
        'kernel': platform.release(),
        'target_m1_8gb': 'not_run',
        'target_android': 'not_run',
    }


def host_report() -> dict:
    report = _host_targets()
    prefix = os.environ.get('PREFIX', '')
    if 'com.termux' in prefix or os.environ.get('ANDROID_ROOT') or os.environ.get('ANDROID_DATA'):
        report['target_android'] = 'host_reports_android_markers'
    if report['system'] == 'Darwin' and report['machine'] in {'arm64', 'aarch64'}:
        _add_darwin_host(report)
    return report


def _add_darwin_host(report: dict) -> None:
    brand, mem_bytes = _darwin_host_details()
    if brand is not None:
        report['darwin_cpu'] = brand
    if mem_bytes is not None:
        report['darwin_mem_bytes'] = mem_bytes
    if brand == 'Apple M1' and mem_bytes == M1_8GB_BYTES:
        report['target_m1_8gb'] = 'host_reports_m1_8gb'



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


def _refuse_promoted_hardware(hardware: dict) -> None:
    if hardware.get('target_m1_8gb') == 'accepted' or hardware.get('target_android') == 'accepted':
        raise QualificationError('receipt refused device acceptance')


def _refuse_unpinned_e2(receipt: dict) -> None:
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


def assert_receipt_honest(receipt: dict) -> None:
    level = receipt.get('evidence_level')
    if level not in {'E1', 'E2'}:
        raise QualificationError(f'receipt refused evidence level {level}')
    if receipt.get('e3_visual_device') != 'not_run' or receipt.get('e4_released') != 'not_run':
        raise QualificationError('receipt refused visual or release acceptance')
    _refuse_promoted_hardware(receipt.get('hardware') or {})
    if level == 'E2':
        _refuse_unpinned_e2(receipt)


def _protection_passed(protection: dict) -> bool:
    return bool(protection.get('pass')) and protection.get('changed_protected_pixels') == 0


def _evidence(inputs: ReceiptInputs) -> tuple[str, bool]:
    level = select_evidence_level(
        record_live=inputs['record_live'],
        weights_match_committed_pin=inputs['weights_match_committed_pin'],
        engine_executed=inputs['engine_executed'],
        dimensions_match=inputs['dimensions_match'],
        protection_pass=_protection_passed(inputs['protection']),
    )
    return level, level == 'E2'


def _limitations() -> list[str]:
    return [
        'Fully locked pixels (protect == 1) are copied from the precision base.',
        'Partial and unlocked pixels keep the engine output.',
        'No grain, sharpening, or beauty smoothing is applied.',
        'E2 records live inference of the committed pin on the reported host.',
        'M1 8GB and Android visual acceptance remain not_run in this receipt.',
        'API fee is zero and no cloud fallback is invoked.',
    ]


def _receipt_fields(inputs: ReceiptInputs, level: str, live: bool) -> dict:
    return {
        'schema_version': SCHEMA_VERSION,
        'task': 'F06',
        'linear': 'MEL-60',
        'command': 'qualify-realesr-general-v3',
        'created_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'evidence_level': level,
        'live_inference': live,
        'e3_visual_device': 'not_run',
        'e4_released': 'not_run',
        'code_sha': code_sha(),
        'hardware': inputs['hardware'],
        'model': inputs['model'],
        'engine': inputs['engine'],
        'input': inputs['source'],
        'output': inputs['output'],
        'protection': inputs['protection'],
        'base_mode': inputs['base_mode'],
        'installer_invoked': inputs['installer_invoked'],
        'runtime': {'wall_elapsed_ms': inputs['elapsed_ms']},
        'postprocess': 'none',
        'cloud_fallback': False,
        'paid_service': False,
        'api_fee': 0,
        'output_image_count': 1,
        'limitations': _limitations(),
    }


def _mark_passed(receipt: dict) -> dict:
    qualification_passed = True
    receipt['pass'] = qualification_passed
    return receipt


def build_receipt(inputs: ReceiptInputs) -> dict:
    level, live = _evidence(inputs)
    receipt = _mark_passed(_receipt_fields(inputs, level, live))
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


def run_upscale(cli: Path, source: Path, destination: Path) -> int:
    executable = _require_absolute_file(cli, 'fidelis CLI path')
    arguments = ['upscale', str(source), str(destination), '--model', MODEL_NAME]
    started = time.perf_counter()
    if os.access(executable, os.X_OK):
        proc = _exec(str(executable), arguments)
    else:
        proc = _bash(str(executable), arguments)
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or '').strip()
        raise QualificationError(f'upscale failed ({proc.returncode}): {detail}')
    if not destination.is_file() or destination.stat().st_size == 0:
        raise QualificationError('upscale produced no output')
    return elapsed_ms


def verify_export(base_png: Path, export_png: Path, mask_npz: Path) -> dict:
    verifier = _require_absolute_file(VERIFIER, 'protected export verifier')
    proc = _exec(sys.executable, [str(verifier), str(base_png), str(export_png), str(mask_npz)])
    try:
        result = json.loads(proc.stdout or '{}')
    except json.JSONDecodeError as exc:
        raise QualificationError(f'protected export verifier returned invalid JSON: {proc.stdout!r}') from exc
    if proc.returncode != 0 or result.get('pass') is not True or result.get('changed_protected_pixels') != 0:
        detail = (proc.stdout or proc.stderr or '').strip()
        raise QualificationError(f'protected export verification failed: {detail}')
    return result


def _require_inputs(input_path: Path, masks_path: Path) -> None:
    if not input_path.is_file():
        raise QualificationError(f'Input not found: {input_path}')
    if not masks_path.is_file():
        raise QualificationError(f'Protect mask not found: {masks_path}')


def _model_state() -> ModelState:
    committed = load_candidate(COMMITTED_CATALOG)
    active = load_candidate(active_catalog())
    home = app_home()
    engine = resolve_engine(home)
    actual_param, actual_bin, installer_invoked = ensure_weights(model_directory(home), active)
    return ModelState(
        committed=committed,
        active=active,
        engine=engine,
        actual_param=actual_param,
        actual_bin=actual_bin,
        installer_invoked=installer_invoked,
        pinned=matches_committed_pin(actual_param, actual_bin, active, committed),
    )


def _pixel_state(source_path: Path, masks_path: Path, base_path: Path | None) -> PixelState:
    source = load_rgb_png(source_path)
    input_height, input_width = source.shape[:2]
    expected_width, expected_height = expected_size(input_width, input_height)
    mask = align_protect_mask(
        load_protect_mask(masks_path), source.shape[:2], (expected_height, expected_width),
    )
    base = prepare_base(source, base_path, (expected_width, expected_height))
    require_expected_scale(base.shape[1], base.shape[0], expected_width, expected_height)
    return PixelState(
        source=source,
        input_width=input_width,
        input_height=input_height,
        expected_width=expected_width,
        expected_height=expected_height,
        mask=mask,
        base=base,
    )


def prepare_inputs(
    input_path: Path,
    masks_path: Path,
    output_path: Path,
    base_path: Path | None,
    record_live: bool,
) -> PreparedRun:
    _require_inputs(input_path, masks_path)
    return PreparedRun(
        input_path=input_path,
        output_path=output_path,
        base_path=base_path,
        record_live=record_live,
        model=_model_state(),
        pixels=_pixel_state(input_path, masks_path, base_path),
    )


def execute_pipeline(prepared: PreparedRun) -> PipelineResult:
    pixels = prepared.pixels
    with tempfile.TemporaryDirectory(prefix='fidelis-f06-') as temporary:
        temp = Path(temporary)
        raw_path = temp / 'texture.png'
        elapsed_ms = run_upscale(resolve_cli(), prepared.input_path, raw_path)
        texture = load_rgb_png(raw_path)
        require_expected_scale(texture.shape[1], texture.shape[0], pixels.expected_width, pixels.expected_height)
        export = composite_protected(pixels.base, texture, pixels.mask)
        protection = _publish(prepared, temp, export, pixels)
    return PipelineResult(elapsed_ms=elapsed_ms, protection=protection)


def _publish(prepared: PreparedRun, temp: Path, export: np.ndarray, pixels: PixelState) -> dict:
    staged = temp / 'export.png'
    base_png = temp / 'base.png'
    mask_npz = temp / 'protect.npz'
    save_rgb_png(staged, export)
    save_rgb_png(base_png, pixels.base)
    np.savez(mask_npz, protect=pixels.mask)
    protection = verify_export(base_png, staged, mask_npz)
    prepared.output_path.parent.mkdir(parents=True, exist_ok=True)
    os.replace(staged, prepared.output_path)
    return protection


def _model_fields(state: ModelState) -> dict:
    return {
        'name': MODEL_NAME,
        'role': state.active['role'],
        'revision': state.active['revision'],
        'committed_revision': state.committed['revision'],
        'license_note': state.active['license_note'],
        'committed_license_note': state.committed['license_note'],
        'param_sha256': state.actual_param,
        'bin_sha256': state.actual_bin,
        'matches_committed_pin': state.pinned,
    }


def _engine_fields(state: ModelState) -> dict:
    return {
        'name': 'realsr-ncnn',
        'path': str(state.engine),
        'sha256': sha256_file(state.engine),
        'scale': SCALE,
    }


def _input_fields(prepared: PreparedRun) -> dict:
    pixels = prepared.pixels
    return {
        'path': str(prepared.input_path),
        'width': pixels.input_width,
        'height': pixels.input_height,
        'sha256': sha256_file(prepared.input_path),
    }


def _output_fields(prepared: PreparedRun) -> dict:
    pixels = prepared.pixels
    return {
        'path': str(prepared.output_path),
        'width': pixels.expected_width,
        'height': pixels.expected_height,
        'expected_width': pixels.expected_width,
        'expected_height': pixels.expected_height,
        'sha256': sha256_file(prepared.output_path),
        'dimensions_match_scale': True,
    }


def _base_mode(base_path: Path | None) -> str:
    if base_path:
        return 'supplied-base'
    return 'integer-replicated-source'


def write_receipt(prepared: PreparedRun, result: PipelineResult, receipt_path: Path) -> dict:
    inputs: ReceiptInputs = {
        'record_live': prepared.record_live,
        'weights_match_committed_pin': prepared.model.pinned,
        'engine_executed': True,
        'dimensions_match': True,
        'protection': result.protection,
        'hardware': host_report(),
        'model': _model_fields(prepared.model),
        'engine': _engine_fields(prepared.model),
        'source': _input_fields(prepared),
        'output': _output_fields(prepared),
        'elapsed_ms': result.elapsed_ms,
        'installer_invoked': prepared.model.installer_invoked,
        'base_mode': _base_mode(prepared.base_path),
    }
    receipt = build_receipt(inputs)
    write_json_atomic(receipt_path, receipt)
    return receipt
