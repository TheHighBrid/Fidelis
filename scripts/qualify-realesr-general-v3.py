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
import importlib.util
import sys
from pathlib import Path


def _load_lib():
    path = Path(__file__).resolve().parent / 'qualify_realesr_lib.py'
    spec = importlib.util.spec_from_file_location('qualify_realesr_lib', path)
    if spec is None or spec.loader is None:
        raise ImportError(f'Cannot load qualification library: {path}')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_lib = _load_lib()
COMMITTED_CATALOG = _lib.COMMITTED_CATALOG
MODEL_NAME = _lib.MODEL_NAME
QualificationError = _lib.QualificationError
UNPINNED_LIVE_NOTE = _lib.UNPINNED_LIVE_NOTE
assert_receipt_honest = _lib.assert_receipt_honest
composite_protected = _lib.composite_protected
load_candidate = _lib.load_candidate
select_evidence_level = _lib.select_evidence_level


def parse_args(argv: list[str] | None) -> argparse.Namespace:
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
    return parser.parse_args(argv)


def run(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    receipt_path = args.receipt or args.output.with_suffix('.receipt.json')
    _lib.invalidate(args.output)
    _lib.invalidate(receipt_path)
    prepared = _lib.prepare_inputs(args.input, args.masks, args.output, args.base, args.record_live)
    result = _lib.execute_pipeline(prepared)
    if args.record_live and not prepared.model.pinned:
        print(UNPINNED_LIVE_NOTE, file=sys.stderr)
    receipt = _lib.write_receipt(prepared, result, receipt_path)
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
