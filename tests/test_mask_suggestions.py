"""Synthetic probability contracts, not real segmentation model/accuracy evidence."""
import base64
import copy
import io
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
import zipfile

import numpy as np
import test_region_http as http_fixture
from fidelis.postprocess.regions import RegionBlend
from fidelis.studio.store import BudgetExceeded,JobStore,RevisionConflict
from fidelis.studio.suggestions import build_suggestion,decode_scores,fill_unclassified,upsample_stripe


def receipt(job):
    return {'schema_version':1,'base_artifact_sha256':job['artifacts']['base']['sha256'],
            'input_dimensions':job['dimensions'],'transform':'full_frame_resize_no_crop_no_rotation',
            'model':{'id':'fixture-only','revision':'test','weights_sha256':'a'*64,'terms_reference':'fixture: no real model used'},
            'labels':[{'name':'Background','region':'unknown'},{'name':'Face','region':'skin'},
                      {'name':'Hair','region':'hair'},{'name':'Garment','region':'fabric'},
                      {'name':'ProtectedHardware','region':'protected'}]}


def probabilities():
    scores=np.zeros((5,4,6),np.float32);scores[0]=.04;scores[1]=.96
    return scores


def encode(scores):
    stream=io.BytesIO();np.savez_compressed(stream,probabilities=scores);return stream.getvalue()


class SuggestionTests(unittest.TestCase):
    def setUp(self):
        self.fixture=http_fixture.HttpTests('test_import_reopen_reblend_export_and_stale_write')
        self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.store=JobStore(self.fixture.temp.name);self.fixture.server.region_store=self.store
        self.base=self.fixture.base;self.texture=self.fixture.texture
        self.job=self.store.create(self.base,self.texture,blend=RegionBlend(skin=1,hair=1,fabric=1))

    def build(self,scores=None,**params):
        return build_suggestion(probabilities() if scores is None else scores,receipt(self.job),
              base_sha256=self.job['artifacts']['base']['sha256'],dimensions=self.job['dimensions'],**params)

    def stage(self,**kwargs):
        return self.store.stage_suggestion(self.job['id'],probabilities(),receipt(self.job),expected_revision=1,**kwargs)

    def test_unknown_low_confidence_and_ambiguous_regions_remain_base(self):
        scores=probabilities();scores[:,1,1]=[.96,.04,0,0,0];scores[:,1,2]=[.3,.7,0,0,0]
        low,record=self.build(scores,boundary=0)
        self.assertEqual(low['confidence'][1,1],0);self.assertEqual(low['confidence'][1,2],0)
        self.assertGreater(low['confidence'][0,0],.9)
        self.assertFalse(record['confidence_is_calibrated']);self.assertFalse(record['live_segmentation_quality_verified'])
        scores[:,1,2]=[0,.5,.5,0,0]
        low,_=self.build(scores,threshold=.5,margin=.1,boundary=0)
        self.assertEqual(low['confidence'][1,2],0)

    def test_grouped_labels_and_boundary_erosion_are_conservative(self):
        scores=np.zeros((5,4,6),np.float32);scores[0]=.05;scores[1]=.5;scores[2]=.45
        meta=receipt(self.job);meta['labels'][2]={'name':'Arm','region':'skin'}
        low,_=build_suggestion(scores,meta,base_sha256=meta['base_artifact_sha256'],dimensions=meta['input_dimensions'])
        self.assertTrue(np.all(low['skin'][1:-1,1:-1]==1));self.assertTrue(np.all(low['skin'][0]==0))
        low,_=self.build(boundary=1)
        stripe=upsample_stripe(low,12,8,0,8)
        self.assertEqual(stripe['skin'].shape,(8,12));self.assertTrue(np.all(stripe['skin'][:2]==0))
        self.assertTrue(np.all(stripe['skin'][2:6,2:10]==1))

    def test_logits_partial_nonfinite_and_wrong_source_are_rejected(self):
        for corrupt in ('partial','nan','range','dtype'):
            scores=probabilities()
            if corrupt=='partial':scores/=2
            if corrupt=='nan':scores[0,0,0]=np.nan
            if corrupt=='range':scores[0,0,0]=2
            if corrupt=='dtype':scores=scores.astype(np.float64)
            with self.assertRaises(ValueError):self.build(scores)
        for field,value in [('base_artifact_sha256','b'*64),('input_dimensions',[6,4]),('transform','cropped')]:
            meta=receipt(self.job);meta[field]=value
            with self.assertRaises(ValueError):build_suggestion(probabilities(),meta,base_sha256=self.job['artifacts']['base']['sha256'],dimensions=self.job['dimensions'])
        for params in ({'threshold':.1},{'margin':float('nan')},{'boundary':True}):
            with self.assertRaises(ValueError):self.build(**params)

    def test_staging_is_read_only_for_master_and_survives_restart(self):
        original=self.job['artifacts']['master']['sha256'];staged=self.stage()
        self.assertEqual(staged['revision'],2);self.assertEqual(staged['artifacts']['master']['sha256'],original)
        self.assertEqual(staged['mask_suggestion']['status'],'staged')
        self.store=JobStore(self.fixture.temp.name)
        overlay=self.store.mask_preview(self.job['id'],2,suggestion=True)
        self.assertGreater(overlay[:,:,3].max(),0)
        updated=self.store.resolve_suggestion(self.job['id'],expected_revision=2,accept=True)
        self.assertEqual(updated['mask_suggestion']['status'],'accepted');self.assertEqual(updated['revision'],3)
        with self.store.open_array(self.job['id'],'master') as master:
            np.testing.assert_array_equal(master[:2],self.base[:2])
            self.assertFalse(np.array_equal(master[2:6,2:10],self.base[2:6,2:10]))
        self.assertFalse(any(k.startswith('suggestion_') for k in updated['artifacts']))

    def test_manual_masks_confidence_erasures_edge_guards_and_protection_win(self):
        shape=(8,12);skin=np.zeros(shape,np.float32);skin[3,3]=.5
        confidence=np.zeros(shape,np.float32);confidence[3,3]=1;confidence[3,4]=1
        protected=np.zeros(shape,np.float32);protected[3,5]=1
        edge=np.zeros(shape,np.float32);edge[3,6]=1
        self.job=self.store.create(self.base,self.texture,masks={'skin':skin,'confidence':confidence,'protected':protected,'edge_guard':edge},blend=RegionBlend(skin=1))
        self.stage(boundary=0);updated=self.store.resolve_suggestion(self.job['id'],expected_revision=2,accept=True)
        for name,pos,value in [('skin',(3,3),.5),('skin',(3,4),0),('protected',(3,5),1),('skin',(3,6),0)]:
            with self.store.open_array(self.job['id'],name) as mask:self.assertEqual(mask[pos],value)
        with self.store.open_array(self.job['id'],'master') as master:np.testing.assert_array_equal(master[3,5],self.base[3,5])
        self.assertEqual(updated['artifacts']['edge_guard'],self.job['artifacts']['edge_guard'])

    def test_stale_stage_and_edit_after_stage_cannot_apply(self):
        self.stage()
        with self.assertRaises(RevisionConflict):self.stage()
        self.store.reblend(self.job['id'],expected_revision=2,blend=RegionBlend(skin=.1))
        with self.assertRaises(RevisionConflict):self.store.resolve_suggestion(self.job['id'],expected_revision=3,accept=True)
        discarded=self.store.resolve_suggestion(self.job['id'],expected_revision=3,accept=False)
        self.assertEqual(discarded['mask_suggestion']['status'],'discarded')

    def test_budget_render_failure_and_corruption_preserve_current_revision(self):
        self.store.disk_budget=1
        with self.assertRaises(BudgetExceeded):self.stage()
        self.assertEqual(self.store.get(self.job['id'])['revision'],1)
        self.store.disk_budget=2*1024**3;staged=self.stage()
        with patch.object(self.store,'_render',side_effect=OSError('fixture render failure')):
            with self.assertRaises(OSError):self.store.resolve_suggestion(self.job['id'],expected_revision=2,accept=True)
        self.assertEqual(self.store.get(self.job['id']),staged)
        path=self.store.root/staged['artifacts']['suggestion_skin']['path'];path.write_bytes(b'corrupt')
        with self.assertRaises(ValueError):self.store.resolve_suggestion(self.job['id'],expected_revision=2,accept=True)
        result=self.store.resolve_suggestion(self.job['id'],expected_revision=2,accept=False)
        self.assertEqual(result['revision'],3)

    def test_packshot_and_model_label_receipt_fail_closed(self):
        strict=self.store.create(self.base,self.texture,profile='packshot_strict',blend=RegionBlend(0,0,0))
        with self.assertRaises(ValueError):self.store.stage_suggestion(strict['id'],probabilities(),receipt(strict),expected_revision=1)
        meta=receipt(self.job);meta['labels'][1]['region']='invented'
        with self.assertRaises(ValueError):build_suggestion(probabilities(),meta,base_sha256=meta['base_artifact_sha256'],dimensions=meta['input_dimensions'])
        meta=receipt(self.job);meta['model']['weights_sha256']='guessed'
        with self.assertRaises(ValueError):build_suggestion(probabilities(),meta,base_sha256=meta['base_artifact_sha256'],dimensions=meta['input_dimensions'])

    def test_npz_header_contract_rejects_object_and_unexpected_members(self):
        np.testing.assert_array_equal(decode_scores(encode(probabilities())),probabilities())
        for scores in (np.zeros((5,4,6),np.float64),np.array([[[object()]]],object),np.zeros((1,4,6),np.float32)):
            with self.assertRaises(ValueError):decode_scores(encode(scores))
        stream=io.BytesIO();np.savez(stream,not_probabilities=probabilities())
        with self.assertRaises(ValueError):decode_scores(stream.getvalue())
        stream=io.BytesIO()
        with zipfile.ZipFile(stream,'w') as archive:archive.writestr('probabilities.npy',b'not numpy')
        with self.assertRaises(ValueError):decode_scores(stream.getvalue())

    def test_http_stage_preview_accept_and_origin_scope(self):
        path='/api/regions/jobs/'+self.job['id']
        payload={'expected_revision':1,'scores':base64.b64encode(encode(probabilities())).decode(),'receipt':receipt(self.job)}
        status,body,_=self.fixture.request(path+'/mask-suggestions',payload)
        self.assertEqual(status,201);data=json.loads(body);self.assertEqual(data['base_artifact_sha256'],receipt(self.job)['base_artifact_sha256'])
        self.assertEqual(self.fixture.request(path+'/suggestion-preview?revision=2')[0],200)
        with self.assertRaises(HTTPError) as caught:self.fixture.request(path+'/accept-suggestion',{'expected_revision':1})
        self.assertEqual(caught.exception.code,409)
        with self.assertRaises(HTTPError) as caught:self.fixture.request(path+'/accept-suggestion',{'expected_revision':2},headers={'Origin':'http://untrusted'})
        self.assertEqual(caught.exception.code,403)
        self.assertEqual(json.loads(self.fixture.request(path+'/accept-suggestion',{'expected_revision':2})[1])['revision'],3)

    def test_local_propose_rejects_wrong_weights_without_staging(self):
        weights = Path(self.fixture.temp.name) / "wrong.onnx"
        weights.write_bytes(b"wrong weights")
        cli = Path(__file__).resolve().parents[1] / "scripts/mask-suggestion.py"
        result = subprocess.run(
            [sys.executable, str(cli), "propose", "--workspace", self.fixture.temp.name,
             "--job", self.job["id"], "--expected-revision", "1", "--weights", str(weights)],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("Weights do not match", result.stderr)
        self.assertEqual(self.store.get(self.job["id"]), self.job)

    def test_cli_describe_stage_discard_preserves_source(self):
        root=Path(self.fixture.temp.name);scores=root/'scores.npz';scores.write_bytes(encode(probabilities()))
        meta=root/'receipt.json';meta.write_text(json.dumps(receipt(self.job)))
        command=[sys.executable,str(Path(__file__).resolve().parents[1]/'scripts/mask-suggestion.py')]
        args=['--workspace',str(root),'--job',self.job['id']]
        described=subprocess.run(command+['describe',*args],capture_output=True,text=True,check=True)
        self.assertEqual(json.loads(described.stdout)['base_artifact_sha256'],receipt(self.job)['base_artifact_sha256'])
        bad=root/'bad.npz';bad.write_bytes(b'not an archive')
        rejected=subprocess.run(command+['stage',*args,'--expected-revision','1','--probabilities',str(bad),'--receipt',str(meta)],capture_output=True,text=True)
        self.assertEqual(rejected.returncode,2);self.assertNotIn('Traceback',rejected.stderr)
        self.assertEqual(self.store.get(self.job['id'])['revision'],1)
        subprocess.run(command+['stage',*args,'--expected-revision','1','--probabilities',str(scores),'--receipt',str(meta)],capture_output=True,text=True,check=True)
        subprocess.run(command+['discard',*args,'--expected-revision','2'],capture_output=True,text=True,check=True)
        with self.store.open_array(self.job['id'],'master') as master:np.testing.assert_array_equal(master,self.base)


if __name__=='__main__':unittest.main()
