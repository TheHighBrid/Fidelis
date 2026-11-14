"""Inventory/freeze contract fixtures; generated test pixels are not a real corpus."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from PIL import Image,PngImagePlugin

from fidelis.eval.corpus_manifest import audit,digest,file_hash,freeze,inspect_image,local_path,verify

REPO=Path(__file__).resolve().parents[1]
PROTOCOL=json.loads((REPO/'config/benchmark/protocol-v1.json').read_text())
SLOTS=json.loads((REPO/'config/benchmark/slots-v1.json').read_text())


class CorpusTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        evidence=self.root/'fixture-permission.txt';evidence.write_text('Fixture declaration only. No real participant, rights approval or production corpus.')
        self.review={'status':'approved','reviewed_by':'test-fixture','reviewed_at':'2026-11-10',
                     'evidence_path':evidence.name,'evidence_sha256':file_hash(evidence)}
        self.manifest={'schema_version':1,'protocol_sha256':digest(PROTOCOL),'slots_sha256':digest(SLOTS),
                       'cases':[],'coverage_review':copy.deepcopy(self.review)}
        for i,slot in enumerate(SLOTS['slots']):
            path=self.root/f'image-{i:02d}.png';Image.new('RGB',(8,6),(i,7,11)).save(path)
            source={'path':path.name,**inspect_image(path)}
            self.manifest['cases'].append({'id':f'test-{i:02d}','role':'production','slot_id':slot['id'],
                'category':slot['category'],'source_kind':'photograph','source':source,
                'leakage_group':f'independent-fixture-{i}',
                'rights':{**self.review,'local_evaluation':True,'subject_consent':'not_required',
                          'remote_processing':'denied','basis':'generated test fixture'},
                'target_dimensions':[16,12],'expected_behavior':'enhance',
                'rois':[{'id':'critical','kind':'text','policy':'preserve','rect':[0,0,4,4]}],
                'known_text':[{'roi_id':'critical','text':'fixture'}],'text_review':'completed'})

    def report(self):return audit(self.manifest,PROTOCOL,SLOTS,self.root)

    def test_complete_fixture_freezes_and_revalidates_without_inference(self):
        report=self.report();self.assertTrue(report['production_ready']);self.assertEqual(report['production_eligible'],60)
        self.assertTrue(all(v=={'calibration':6,'held_out':6} for v in report['coverage'].values()))
        lock=freeze(self.manifest,PROTOCOL,SLOTS,self.root)
        self.assertEqual(lock['record_type'],'unsigned_corpus_lock')
        self.assertTrue(verify(lock,self.root)['production_ready'])
        self.assertEqual(lock['lock_sha256'],freeze(self.manifest,PROTOCOL,SLOTS,self.root)['lock_sha256'])

    def test_tracked_inventory_is_regression_only_and_reports_all_missing(self):
        manifest=json.loads((REPO/'config/benchmark/inventory-v1.json').read_text())
        report=audit(manifest,PROTOCOL,SLOTS,REPO)
        self.assertEqual(report,json.loads((REPO/'config/benchmark/inventory-audit-v1.json').read_text()))
        self.assertFalse(report['production_ready']);self.assertEqual(report['production_eligible'],0)
        self.assertEqual(report['regression_available'],8);self.assertEqual(len(report['missing_slots']),60)
        self.assertTrue(all(case['role']=='regression' and not case['eligible'] for case in report['cases']))
        self.assertTrue(all('source_fingerprint_changed' not in case['blockers'] for case in report['cases']))
        with self.assertRaises(ValueError):freeze(manifest,PROTOCOL,SLOTS,REPO)

    def test_permissions_are_explicit_and_remote_denial_does_not_block_local(self):
        self.assertTrue(self.report()['production_ready'])
        for field,value in (('status','unknown'),('local_evaluation',False),('subject_consent','unknown'),
                            ('basis',None),('evidence_sha256','0'*64)):
            original=copy.deepcopy(self.manifest['cases'][0]['rights'])
            self.manifest['cases'][0]['rights'][field]=value
            self.assertFalse(self.report()['production_ready'],field)
            self.manifest['cases'][0]['rights']=original
        self.manifest['coverage_review']['status']='pending'
        self.assertIn('coverage_review_unapproved',self.report()['global_blockers'])

    def test_changed_source_or_permission_evidence_invalidates_lock(self):
        lock=freeze(self.manifest,PROTOCOL,SLOTS,self.root)
        (self.root/'fixture-permission.txt').write_text('changed')
        with self.assertRaises(ValueError):verify(lock,self.root)
        self.manifest['coverage_review']['evidence_sha256']=file_hash(self.root/'fixture-permission.txt')
        Image.new('RGB',(8,6),(255,255,255)).save(self.root/'image-00.png')
        self.assertIn('source_fingerprint_changed',self.report()['cases'][0]['blockers'])

    def test_missing_source_or_invalid_dimensions_fail_readiness(self):
        (self.root/'image-00.png').unlink()
        self.assertIn('source_missing',self.report()['cases'][0]['blockers'])
        self.manifest['cases'][1]['target_dimensions']=None
        self.assertIn('target_dimensions_missing_or_invalid',self.report()['cases'][1]['blockers'])
        with self.assertRaises(ValueError):freeze(self.manifest,PROTOCOL,SLOTS,self.root)

    def test_duplicate_and_reencoded_pixel_copies_do_not_count_as_new_cases(self):
        src=self.root/'image-00.png';dst=self.root/'image-01.png'
        dst.write_bytes(src.read_bytes());self.manifest['cases'][1]['source']={'path':dst.name,**inspect_image(dst)}
        self.assertIn('duplicate_sha256',self.report()['cases'][1]['blockers'])
        info=PngImagePlugin.PngInfo();info.add_text('different_encoding','same_pixels')
        with Image.open(src) as image:image.save(dst,pnginfo=info)
        self.manifest['cases'][1]['source']={'path':dst.name,**inspect_image(dst)}
        report=self.report();self.assertIn('duplicate_pixel_sha256',report['cases'][1]['blockers'])
        self.assertNotIn('duplicate_sha256',report['cases'][1]['blockers']);self.assertFalse(report['production_ready'])

    def test_related_subject_product_or_capture_cannot_cross_splits(self):
        self.manifest['cases'][6]['leakage_group']=self.manifest['cases'][0]['leakage_group']
        self.assertIn('group_crosses_splits',self.report()['cases'][6]['blockers'])
        with self.assertRaises(ValueError):freeze(self.manifest,PROTOCOL,SLOTS,self.root)

    def test_slot_plan_and_manifest_digests_detect_reassignment(self):
        slots=copy.deepcopy(SLOTS);slots['slots'][0]['split']='held_out'
        with self.assertRaises(ValueError):audit(self.manifest,PROTOCOL,slots,self.root)
        protocol=copy.deepcopy(PROTOCOL);protocol['split']['calibration']=29
        with self.assertRaises(ValueError):audit(self.manifest,protocol,SLOTS,self.root)
        lock=freeze(self.manifest,PROTOCOL,SLOTS,self.root);lock['manifest']['cases'][0]['target_dimensions']=[32,24]
        with self.assertRaisesRegex(ValueError,'digest'):verify(lock,self.root)

    def test_rois_and_transcripts_are_not_invented_or_silently_clamped(self):
        case=self.manifest['cases'][0];case['rois'][0]['rect']=[7,0,4,4]
        self.assertIn('roi_outside_source',self.report()['cases'][0]['blockers'])
        case['rois'][0]['rect']=[0,0,4,4];case['known_text']=[]
        self.assertIn('text_roi_transcript_missing',self.report()['cases'][0]['blockers'])
        case['rois']=[]
        self.assertIn('critical_rois_unreviewed',self.report()['cases'][0]['blockers'])

    def test_absolute_parent_and_symlink_asset_escapes_are_rejected(self):
        for value in ('../outside.png',str(self.root/'image-00.png')):
            with self.assertRaises(ValueError):local_path(self.root,value)
        with tempfile.TemporaryDirectory() as outside:
            path=Path(outside)/'private.png';Image.new('RGB',(1,1)).save(path)
            (self.root/'escape.png').symlink_to(path)
            with self.assertRaises(ValueError):local_path(self.root,'escape.png')
        self.manifest['cases'][0]['source']['path']='../not-authorized.png'
        self.assertIn('source_invalid_or_unavailable',self.report()['cases'][0]['blockers'])

    def test_cli_audit_not_ready_exit_and_exclusive_freeze_verify(self):
        manifest=self.root/'manifest.json';manifest.write_text(json.dumps(self.manifest))
        cli=[sys.executable,str(REPO/'scripts/benchmark-corpus.py')]
        common=['--root',str(self.root),'--protocol',str(REPO/'config/benchmark/protocol-v1.json'),
                '--slots',str(REPO/'config/benchmark/slots-v1.json')]
        output=self.root/'corpus.lock.json'
        result=subprocess.run(cli+['freeze',str(manifest),*common,'--output',str(output)],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr);original=output.read_bytes()
        again=subprocess.run(cli+['freeze',str(manifest),*common,'--output',str(output)],capture_output=True,text=True)
        self.assertEqual(again.returncode,2);self.assertEqual(output.read_bytes(),original)
        result=subprocess.run(cli+['verify',str(output),'--root',str(self.root)],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.manifest['cases']=[];manifest.write_text(json.dumps(self.manifest))
        result=subprocess.run(cli+['audit',str(manifest),*common,'--require-ready'],capture_output=True,text=True)
        self.assertEqual(result.returncode,1)
        self.assertFalse(json.loads(result.stdout)['production_ready'])
        result=subprocess.run(cli+['freeze',str(manifest),*common,'--output',str(self.root/'missing.lock')],capture_output=True,text=True)
        self.assertEqual(result.returncode,2);self.assertFalse((self.root/'missing.lock').exists())

    def test_malformed_json_duplicate_ids_and_regression_promotion_fail(self):
        duplicate=copy.deepcopy(self.manifest);duplicate['cases'][1]['id']=duplicate['cases'][0]['id']
        with self.assertRaises(ValueError):audit(duplicate,PROTOCOL,SLOTS,self.root)
        self.manifest['cases'][0]['role']='regression'
        with self.assertRaises(ValueError):self.report()
        self.manifest['cases'][0]['role']='production';self.manifest['cases'][0]['source_kind']='synthetic'
        self.assertIn('not_a_photographic_production_case',self.report()['cases'][0]['blockers'])
        malformed=self.root/'bad.json';malformed.write_text('{"schema_version":1,"schema_version":1}')
        result=subprocess.run([sys.executable,str(REPO/'scripts/benchmark-corpus.py'),'audit',str(malformed)],capture_output=True,text=True)
        self.assertEqual(result.returncode,2);self.assertIn('Duplicate JSON key',result.stderr)


if __name__=='__main__':unittest.main()
