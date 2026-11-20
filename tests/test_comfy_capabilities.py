"""Registry inventory does not mistake declared candidates for installed models."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from fidelis.studio.capabilities import inventory


class CapabilityTests(unittest.TestCase):
    def test_missing_weights_are_not_reported_installed(self):
        repo=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as home:
            with patch.dict('os.environ',{'FIDELIS_ENGINE':str(Path(home)/'missing')}):
                report=inventory(repo,home)
        self.assertFalse(report['ncnn_executable'])
        self.assertTrue(all(not item['installed'] for item in report['candidates']))
        self.assertTrue(all(not item['quality_certified'] for item in report['candidates']))

    def test_registered_checksums_detect_tampering_without_quality_claims(self):
        repo=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as home:
            model=Path(home)/'runtime/models-example';model.mkdir(parents=True)
            (model/'x4.param').write_bytes(b'param')
            (model/'x4.bin').write_bytes(b'weights')
            (model/'fidelis-model.json').write_text(json.dumps({'name':'example','sha256':{
                'param':hashlib.sha256(b'param').hexdigest(),'bin':hashlib.sha256(b'weights').hexdigest()}}))
            row=inventory(repo,home)['registered_models'][0]
            self.assertEqual(row['integrity'],'matched');self.assertFalse(row['inference_verified'])
            (model/'x4.bin').write_bytes(b'tampered')
            self.assertEqual(inventory(repo,home)['registered_models'][0]['integrity'],'mismatch')

if __name__=='__main__':unittest.main()
