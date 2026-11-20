"""Read-only inventory; installed files never imply certified inference quality."""
import csv
import importlib.util
import json
import os
import platform
import shutil
from pathlib import Path

from fidelis.studio.provenance import audit_model_provenance, confined_local_path
from fidelis.studio.store import sha256


def inventory(repo_root, app_home=None):
    app_home = Path(app_home or os.environ.get('FIDELIS_HOME', str(Path.home()/'.local/share/fidelis')))
    provenance = audit_model_provenance(repo_root, app_home)
    runtime = app_home / 'runtime'
    models = []
    candidates_path = Path(repo_root) / 'config/photo-candidates.tsv'
    with candidates_path.open() as stream:
        rows = csv.reader((line for line in stream if not line.startswith('#')), delimiter='\t')
        for row in rows:
            if not row:
                continue
            name, role, revision, folder, param_hash, bin_hash, license_note = row
            directory = runtime / folder
            param = confined_local_path(app_home, directory.relative_to(app_home) / 'x4.param')
            binary = confined_local_path(app_home, directory.relative_to(app_home) / 'x4.bin')
            present = param.is_file() and binary.is_file()
            valid = present and sha256(param) == param_hash and sha256(binary) == bin_hash
            models.append({'name':name, 'role':role, 'revision':revision,
                           'installed':present, 'integrity': 'matched' if valid else ('mismatch' if present else 'missing'),
                           'license_note':license_note, 'inference_verified':False, 'quality_certified':False})
    registered = []
    for metadata in runtime.glob('models-*/fidelis-model.json'):
        try:
            data = json.loads(confined_local_path(app_home, metadata.relative_to(app_home)).read_text())
            hashes = data.get('sha256', {})
            weights = {key: confined_local_path(app_home, (metadata.parent/name).relative_to(app_home))
                       for name,key in (('x4.param','param'),('x4.bin','bin'))}
            matched = all(path.is_file() and sha256(path) == hashes.get(key)
                          for key,path in weights.items())
            registered.append({'name':str(data.get('name', metadata.parent.name)), 'integrity':'matched' if matched else 'mismatch',
                               'inference_verified':False, 'quality_certified':False})
        except (ValueError,OSError):
            registered.append({'name':metadata.parent.name,'integrity':'invalid_metadata','inference_verified':False,'quality_certified':False})
    engine = Path(os.environ.get('FIDELIS_ENGINE', str(runtime/'realsr-ncnn')))
    if not os.access(engine, os.X_OK) and os.access(runtime/'realsr-ncnn-vulkan', os.X_OK):
        engine = runtime/'realsr-ncnn-vulkan'
    return {'schema_version':1, 'platform':platform.system(), 'architecture':platform.machine(),
            'ncnn_executable':engine.is_file() and os.access(engine,os.X_OK),
            'torch_importable':importlib.util.find_spec('torch') is not None,
            'nvidia_smi_present':shutil.which('nvidia-smi') is not None,
            'candidates':models, 'registered_models':registered,
            'model_provenance':provenance}
