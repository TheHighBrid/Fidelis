"""Read-only inventory; installed files never imply certified inference quality."""
import csv
import importlib.util
import json
import os
from pathlib import Path
import platform
import shutil

from fidelis.studio.provenance import audit_model_provenance
from fidelis.studio.store import sha256


def inventory(repo_root, app_home=None):
    app_home = Path(app_home or os.environ.get('FIDELIS_HOME', str(Path.home()/'.local/share/fidelis')))
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
            param, binary = directory/'x4.param', directory/'x4.bin'
            present = param.is_file() and binary.is_file()
            valid = present and sha256(param) == param_hash and sha256(binary) == bin_hash
            models.append({'name':name, 'role':role, 'revision':revision,
                           'installed':present, 'integrity': 'matched' if valid else ('mismatch' if present else 'missing'),
                           'license_note':license_note, 'inference_verified':False, 'quality_certified':False})
    registered = []
    for metadata in runtime.glob('models-*/fidelis-model.json'):
        try:
            data = json.loads(metadata.read_text())
            hashes = data.get('sha256', {})
            matched = all((metadata.parent/name).is_file() and sha256(metadata.parent/name) == hashes.get(key)
                          for name,key in (('x4.param','param'),('x4.bin','bin')))
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
            'model_provenance':audit_model_provenance(repo_root, app_home)}
