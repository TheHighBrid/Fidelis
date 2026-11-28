"""Stage only catalog-cleared, byte-verified weights for redistribution."""
import hashlib
import json
import shutil
from pathlib import Path


def _verified_notice(root, model):
    identity = model['model_id']
    if not isinstance(identity, str) or Path(identity).name != identity:
        raise ValueError('Invalid model notice identity')
    notice = root / 'config/model-licenses' / (identity + '.txt')
    if (notice.is_symlink() or not notice.is_file()
            or not notice.resolve().is_relative_to(root.resolve())):
        raise ValueError('Missing or unsafe model license notice: ' + identity)
    expected = model.get('terms', {}).get('packaged_notice_sha256')
    if hashlib.sha256(notice.read_bytes()).hexdigest() != expected:
        raise ValueError('Model license notice checksum mismatch: ' + identity)
    return notice, expected


def stage_models(repo_root, runtime, destination):
    root, runtime, destination = map(Path, (repo_root, runtime, destination))
    catalog = json.loads((root / 'config/model-provenance-v1.json').read_text())
    destination.mkdir(parents=True, exist_ok=True)
    by_folder = {Path(m['local_relative_dir']).name: m for m in catalog['models']
                 if m.get('local_relative_dir')}
    receipt = {'schema_version': 1, 'included': [], 'excluded': []}
    for folder in sorted(runtime.glob('models-*')):
        model = by_folder.get(folder.name)
        terms = model.get('terms', {}) if model else {}
        if terms.get('production_terms_cleared') is not True:
            receipt['excluded'].append({'folder': folder.name, 'reason': 'terms_not_cleared'})
            continue
        # Each cleared model requires an explicit packaged license notice.
        notice, notice_sha = _verified_notice(root, model)
        if folder.is_symlink() or not folder.is_dir():
            raise ValueError('Invalid model directory or missing license notice: ' + folder.name)
        weights = model.get('weights', {})
        if not weights:
            raise ValueError('Missing model weight hashes: ' + folder.name)
        verified = []
        for name, digest in weights.items():
            source = folder / name
            if Path(name).name != name or source.is_symlink() or not source.is_file():
                raise ValueError('Invalid weight path: ' + str(source))
            if hashlib.sha256(source.read_bytes()).hexdigest() != digest:
                raise ValueError('Model weight checksum mismatch: ' + str(source))
            verified.append(source)
        target = destination / folder.name
        target.mkdir()
        for source in verified:
            shutil.copyfile(source, target / source.name)
        shutil.copyfile(notice, target / 'LICENSE.txt')
        if hashlib.sha256((target / 'LICENSE.txt').read_bytes()).hexdigest() != notice_sha:
            raise ValueError('Staged model license notice checksum mismatch: ' + folder.name)
        (target / 'redistribution-provenance.json').write_text(json.dumps(model, indent=2) + '\n')
        receipt['included'].append({'model_id': model['model_id'], 'folder': folder.name,
                                    'weights': weights, 'license': terms['license']})
    (destination / 'redistribution-receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    return receipt
