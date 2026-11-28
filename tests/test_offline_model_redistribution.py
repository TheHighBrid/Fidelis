import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from fidelis.studio.offline_models import stage_models


class OfflineRedistributionTests(unittest.TestCase):
    def test_verified_cleared_model_only_and_tampering_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'config/model-licenses').mkdir(parents=True)
            for name in ('safe', 'unknown'):
                folder = root / 'runtime' / ('models-' + name)
                folder.mkdir(parents=True)
                (folder / 'x4.bin').write_bytes(b'weights')
                (folder / 'private-extra').write_text('must not ship')
            (root / 'config/model-licenses/safe.txt').write_text('Required notice')
            model = {'model_id': 'safe', 'local_relative_dir': 'runtime/models-safe',
                     'weights': {'x4.bin': hashlib.sha256(b'weights').hexdigest()},
                     'terms': {'production_terms_cleared': True, 'license': 'BSD-3-Clause',
                               'packaged_notice_sha256': hashlib.sha256(b'Required notice').hexdigest()}}
            (root / 'config/model-provenance-v1.json').write_text(json.dumps({'models': [model, {'local_relative_dir': None}]}))
            out = root / 'out'
            receipt = stage_models(root, root / 'runtime', out)
            self.assertEqual(len(receipt['included']), 1)
            self.assertEqual(len(receipt['excluded']), 1)
            self.assertTrue((out / 'models-safe/LICENSE.txt').is_file())
            self.assertFalse((out / 'models-safe/private-extra').exists())
            self.assertFalse((out / 'models-unknown').exists())
            (root / 'runtime/models-safe/x4.bin').write_bytes(b'tampered')
            with self.assertRaisesRegex(ValueError, 'checksum'):
                stage_models(root, root / 'runtime', root / 'bad')
            (root / 'config/model-licenses/safe.txt').unlink()
            with self.assertRaisesRegex(ValueError, 'notice'):
                stage_models(root, root / 'runtime', root / 'missing-notice')
