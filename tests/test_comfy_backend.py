"""ComfyUI protocol tests against an HTTP fixture, not GPU inference evidence."""
import copy
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import hashlib
import io
import json
from pathlib import Path
import tempfile
import subprocess
import sys
import threading
import unittest
import uuid

import numpy as np
from PIL import Image

from fidelis.studio.comfy import BackendUnavailable,CacheBudgetExceeded,ComfyTextureBackend,GenerationCancelled,SubmissionUnknown,canonical_hash,validate_workflow
from fidelis.studio.png import write_rgb_png
from fidelis.studio.store import JobStore,RevisionConflict
from fidelis.postprocess.regions import RegionBlend

SCHEMA={
 'LoadImage':{'input':{'required':{'image':[['placeholder.png'],{}]}}},
 'FixtureTexture':{'input':{'required':{'image':['IMAGE']}}},
 'SaveImage':{'input':{'required':{'images':['IMAGE'],'filename_prefix':['STRING']}}}}
BUNDLE={'schema_version':1,'family':'sdxl','input_node':'1','output_node':'3','workflow':{
 '1':{'class_type':'LoadImage','inputs':{'image':'placeholder.png'}},
 '2':{'class_type':'FixtureTexture','inputs':{'image':['1',0]}},
 '3':{'class_type':'SaveImage','inputs':{'images':['2',0],'filename_prefix':'test'}}}}


class ComfyTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.source=np.full((8,12,3),60,np.uint8)
        self.output=np.full((8,12,3),180,np.uint8)
        self.state={'submits':0,'history':{},'mode':'success'}
        state=self.state;owner=self
        class Handler(BaseHTTPRequestHandler):
            def reply(self,data,status=200,ctype='application/json'):
                raw=data if isinstance(data,bytes) else json.dumps(data).encode()
                self.send_response(status);self.send_header('Content-Type',ctype)
                self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
            def do_GET(self):
                if self.path=='/object_info':return self.reply(SCHEMA)
                if self.path=='/system_stats':return self.reply({'devices':[{'type':'fixture'}]})
                if self.path.startswith('/history'):
                    return self.reply({} if state['mode']=='pending' else state['history'])
                if self.path=='/queue':return self.reply({'queue_pending':[],'queue_running':[]})
                if self.path.startswith('/view?'):
                    image=io.BytesIO();Image.fromarray(owner.output).save(image,format='PNG')
                    return self.reply(image.getvalue(),ctype='image/png')
                self.reply({},404)
            def do_POST(self):
                body=self.rfile.read(int(self.headers['Content-Length']))
                if self.path=='/upload/image':return self.reply({'name':'base.png','subfolder':'isolated','type':'input'})
                if self.path=='/prompt':
                    state['submits']+=1;payload=json.loads(body)
                    state['history']['prompt-1']={'prompt':[0,'prompt-1',payload['prompt'],payload['extra_data']],
                       'status':{'completed':True,'status_str':'success'},
                       'outputs':{'3':{'images':[{'filename':'out.png','subfolder':'','type':'output'}]}}}
                    if state['mode']=='error':state['history']['prompt-1']['status']['status_str']='error'
                    if state['mode']=='ambiguous':return self.reply({'error':'connection lost after queueing'},500)
                    if state['mode']=='malformed_ack':return self.reply(state['ack'])
                    return self.reply({'prompt_id':'prompt-1'})
                self.reply({},404)
            def log_message(self,*args):pass
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.addCleanup(self.stop)
        self.backend=ComfyTextureBackend(self.temp.name,f'http://127.0.0.1:{self.server.server_port}',poll_interval=0)
        self.addCleanup(self.backend.close)
        self.run_id=str(uuid.uuid4())
    def stop(self):
        self.server.shutdown();self.server.server_close();self.thread.join()

    def test_success_cache_and_recipe_no_duplicate_submission(self):
        output,record=self.backend.run(self.source,BUNDLE,run_id=self.run_id)
        np.testing.assert_array_equal(output,self.output)
        self.assertEqual(record['status'],'completed')
        self.assertFalse(record['live_quality_verified'])
        again,_=self.backend.run(self.source,BUNDLE,run_id=self.run_id)
        np.testing.assert_array_equal(again,output)
        self.assertEqual(self.state['submits'],1)

    def test_budget_failure_preserves_identity_and_existing_files(self):
        root=Path(self.temp.name)
        first,first_record=self.backend.run(self.source,BUNDLE,run_id=self.run_id)
        cache=root/f'{self.run_id}.png'
        original=cache.read_bytes()
        self.backend.cache_budget=len(original)+1
        other=str(uuid.uuid4())
        with self.assertRaises(CacheBudgetExceeded):
            self.backend.run(self.source,BUNDLE,run_id=other)
        self.assertEqual(self.backend._get(other)['status'],'submitted')
        self.assertEqual(cache.read_bytes(),original)
        self.assertFalse(list(root.glob('*.pending')))
        self.assertFalse((root/f'{other}.png').exists())
        again,record=self.backend.run(self.source,BUNDLE,run_id=self.run_id)
        np.testing.assert_array_equal(again,first)
        self.assertEqual(record,first_record)
        self.backend.cache_budget=2*len(original)
        output,record=self.backend.run(self.source,BUNDLE,run_id=other)
        np.testing.assert_array_equal(output,self.output)
        self.assertEqual(record['status'],'completed')
        self.assertEqual(self.state['submits'],2)
        self.assertEqual(self.backend._cache_bytes(),2*len(original))

    def test_orphan_and_staging_payloads_count_against_budget(self):
        root=Path(self.temp.name)
        orphan=root/'orphan.png'; orphan.write_bytes(b'x'*30)
        staged=root/'abandoned.pending'; staged.write_bytes(b'x'*20)
        self.backend.cache_budget=50
        with self.assertRaises(CacheBudgetExceeded):
            self.backend.run(self.source,BUNDLE,run_id=self.run_id)
        self.assertEqual(self.backend._cache_bytes(),50)
        self.assertEqual(orphan.read_bytes(),b'x'*30)
        self.assertEqual(staged.read_bytes(),b'x'*20)

    def test_two_backend_instances_share_atomic_publication_budget(self):
        stream=io.BytesIO();write_rgb_png(self.output,stream)
        self.backend.cache_budget=len(stream.getvalue())
        peer=ComfyTextureBackend(self.temp.name,self.backend.address,poll_interval=0,
                                 cache_budget=self.backend.cache_budget)
        self.addCleanup(peer.close)
        barrier=threading.Barrier(2)
        def execute(backend):
            run_id=str(uuid.uuid4())
            barrier.wait(timeout=2)
            try:
                backend.run(self.source,BUNDLE,run_id=run_id)
                return 'completed',run_id
            except CacheBudgetExceeded:
                return 'submitted',run_id
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(execute,(self.backend,peer)))
        self.assertCountEqual([state for state,_ in results],['completed','submitted'])
        for state,run_id in results:
            self.assertEqual(self.backend._get(run_id)['status'],state)
        self.assertEqual(self.backend._cache_bytes(),self.backend.cache_budget)
        self.assertFalse(list(Path(self.temp.name).glob('*.pending')))

    def test_invalid_cache_budget_rejected(self):
        for limit in (0,-1,True,1.5):
            with self.assertRaises(ValueError):
                ComfyTextureBackend(self.temp.name,self.backend.address,cache_budget=limit)

    def test_ambiguous_submission_reconciles_without_resubmitting(self):
        self.state['mode']='ambiguous'
        with self.assertRaises(SubmissionUnknown):self.backend.run(self.source,BUNDLE,run_id=self.run_id)
        output,_=self.backend.run(self.source,BUNDLE,run_id=self.run_id)
        np.testing.assert_array_equal(output,self.output)
        self.assertEqual(self.state['submits'],1)

    def test_malformed_prompt_acknowledgements_reconcile_without_duplicate_submission(self):
        # HTTP 200 is not proof that the prompt ID was returned. A retry could
        # generate the same image twice if the worker already queued the prompt.
        for acknowledgement in ([], None, 'prompt-1', {}, {'prompt_id': ''},
                                {'prompt_id': 123}, {'prompt_id': '   '},
                                {'prompt_id': 'prompt-1', 'error': 'uncertain'}):
            with self.subTest(acknowledgement=acknowledgement):
                run_id = str(uuid.uuid4())
                self.state['mode'] = 'malformed_ack'
                self.state['ack'] = acknowledgement
                before = self.state['submits']
                with self.assertRaisesRegex(SubmissionUnknown, 'prompt ID'):
                    self.backend.run(self.source, BUNDLE, run_id=run_id)
                self.assertEqual(self.backend._get(run_id)['status'], 'submission_unknown')
                self.assertEqual(self.state['submits'], before + 1)
                output, record = self.backend.run(self.source, BUNDLE, run_id=run_id)
                np.testing.assert_array_equal(output, self.output)
                self.assertEqual(record['status'], 'completed')
                self.assertEqual(self.state['submits'], before + 1)

    def test_malformed_reconciliation_payloads_never_resubmit(self):
        self.state['mode'] = 'malformed_ack'
        self.state['ack'] = {}
        with self.assertRaises(SubmissionUnknown):
            self.backend.run(self.source, BUNDLE, run_id=self.run_id)
        self.assertEqual(self.state['submits'], 1)
        original_json = self.backend._json
        for route, payload in (('/queue', []), ('/queue', {'queue_pending': None}),
                               ('/history?max_items=1000', [])):
            with self.subTest(route=route, payload=payload):
                self.backend._json = lambda method, requested, **kwargs: (
                    payload if requested == route else original_json(method, requested, **kwargs))
                try:
                    with self.assertRaises(SubmissionUnknown):
                        self.backend.run(self.source, BUNDLE, run_id=self.run_id)
                finally:
                    self.backend._json = original_json
                self.assertEqual(self.backend._get(self.run_id)['status'], 'submission_unknown')
                self.assertEqual(self.state['submits'], 1)
        output, record = self.backend.run(self.source, BUNDLE, run_id=self.run_id)
        np.testing.assert_array_equal(output, self.output)
        self.assertEqual(record['status'], 'completed')
        self.assertEqual(self.state['submits'], 1)

    def test_timeout_resume_polls_existing_prompt(self):
        self.state['mode']='pending'
        with self.assertRaises(TimeoutError):self.backend.run(self.source,BUNDLE,run_id=self.run_id,deadline_seconds=.01)
        self.state['mode']='success'
        self.backend.run(self.source,BUNDLE,run_id=self.run_id)
        self.assertEqual(self.state['submits'],1)

    def test_wrong_dimensions_are_rejected_without_resizing(self):
        self.output=np.zeros((9,12,3),np.uint8)
        with self.assertRaisesRegex(ValueError,'dimensions'):
            self.backend.run(self.source,BUNDLE,run_id=self.run_id)
        self.assertFalse((Path(self.temp.name)/f'{self.run_id}.png').exists())

    def test_execution_error_and_recipe_conflict(self):
        self.state['mode']='error'
        with self.assertRaises(RuntimeError):self.backend.run(self.source,BUNDLE,run_id=self.run_id)
        with self.assertRaisesRegex(ValueError,'different recipe'):
            self.backend.run(self.source+1,BUNDLE,run_id=self.run_id)
        self.assertEqual(self.state['submits'],1)

    def test_schema_validation_rejects_missing_class_and_cycles(self):
        for mutate in ('class','cycle','input'):
            bundle=copy.deepcopy(BUNDLE)
            if mutate=='class':bundle['workflow']['2']['class_type']='UninstalledModel'
            if mutate=='cycle':bundle['workflow']['2']['inputs']['image']=['3',0]
            if mutate=='input':bundle['workflow']['3']['inputs']={}
            with self.assertRaises(ValueError):validate_workflow(bundle,SCHEMA)
        self.assertEqual(self.state['submits'],0)

    def test_boolean_workflow_link_indices_fail_before_submission(self):
        for index in (True, False):
            bundle = copy.deepcopy(BUNDLE)
            bundle['workflow']['2']['inputs']['image'] = ['1', index]
            with self.subTest(index=index), self.assertRaisesRegex(ValueError, 'boolean'):
                validate_workflow(bundle, SCHEMA)
        self.assertEqual(self.state['submits'], 0)

    def test_workflow_link_output_slots_match_installed_schema(self):
        schema = copy.deepcopy(SCHEMA)
        schema['LoadImage']['output'] = ['IMAGE']
        schema['FixtureTexture']['output'] = ['IMAGE']
        self.assertEqual(validate_workflow(BUNDLE, schema), BUNDLE['workflow'])
        for node_id, input_name in (('2', 'image'), ('3', 'images')):
            for invalid_index in (1, 100):
                bundle = copy.deepcopy(BUNDLE)
                bundle['workflow'][node_id]['inputs'][input_name][1] = invalid_index
                with self.subTest(node_id=node_id, index=invalid_index):
                    with self.assertRaisesRegex(ValueError, 'output index exceeds'):
                        validate_workflow(bundle, schema)
        self.assertEqual(self.state['submits'], 0)

    def test_workflow_link_to_invalid_upstream_node_fails_closed(self):
        bundle = copy.deepcopy(BUNDLE)
        bundle['workflow']['2'] = None
        with self.assertRaisesRegex(TypeError, 'Invalid workflow node'):
            validate_workflow(bundle, SCHEMA)
        self.assertEqual(self.state['submits'], 0)

    def test_invalid_endpoint_nodes_are_rejected_before_graph_submission(self):
        for node_id in ('1', '3'):
            bundle = copy.deepcopy(BUNDLE)
            bundle['workflow'][node_id] = None
            with self.subTest(node_id=node_id), self.assertRaises(ValueError):
                validate_workflow(bundle, SCHEMA)
        self.assertEqual(self.state['submits'], 0)

    def test_cancellation_before_prompt_is_not_resubmitted(self):
        checks = iter([False, False, False, True])
        with self.assertRaises(GenerationCancelled):
            self.backend.run(self.source, BUNDLE, run_id=self.run_id,
                             cancelled=lambda: next(checks))
        with self.assertRaises(SubmissionUnknown):
            self.backend.run(self.source, BUNDLE, run_id=self.run_id)
        self.assertEqual(self.state['submits'], 0)

    def test_remote_destination_rejected(self):
        with self.assertRaises(ValueError):ComfyTextureBackend(self.temp.name,'https://example.com')

    def test_cli_run_and_repeat_use_one_submission(self):
        root=Path(self.temp.name)
        workflow=root/'workflow.json';workflow.write_text(json.dumps(BUNDLE))
        source=root/'base.png';Image.fromarray(self.source).save(source)
        output=root/'texture.png'
        command=[sys.executable,str(Path(__file__).resolve().parents[1]/'scripts/generate-texture.py'),
                 str(workflow),str(output),'--source',str(source),'--runs',str(root/'cli-runs'),
                 '--address',self.backend.address]
        first=subprocess.run(command,capture_output=True,text=True,check=True)
        second=subprocess.run(command,capture_output=True,text=True,check=True)
        self.assertEqual(json.loads(first.stdout)['run_id'],json.loads(second.stdout)['run_id'])
        self.assertEqual(self.state['submits'],1)
        with Image.open(output) as image:np.testing.assert_array_equal(np.array(image),self.output)
        self.assertEqual(json.loads(output.with_suffix('.png.recipe.json').read_text())['status'],'completed')

    def test_default_cli_identity_distinguishes_same_bytes_and_resumes_old_runs(self):
        address = self.backend.address
        old_identity = canonical_hash({'source': hashlib.sha256(self.source.tobytes()).hexdigest(),
                                       'bundle': BUNDLE, 'address': address})
        legacy_id = str(uuid.uuid5(uuid.NAMESPACE_URL, old_identity))
        self.backend.run(self.source, BUNDLE, run_id=legacy_id)
        self.assertEqual(self.backend.default_cli_run_id(self.source, BUNDLE, address), legacy_id)
        other_grid = self.source.reshape(12, 8, 3)
        other_id = self.backend.default_cli_run_id(other_grid, BUNDLE, address)
        self.assertNotEqual(other_id, legacy_id)
        self.output = self.output.reshape(12, 8, 3)
        self.backend.run(other_grid, BUNDLE, run_id=other_id)
        self.assertEqual(self.state['submits'], 2)

    def test_replace_texture_keeps_masks_and_detects_stale_revision(self):
        store=JobStore(Path(self.temp.name)/'jobs')
        locked=np.zeros((8,12),np.float32);locked[:,:3]=1
        job=store.create(self.source,self.source,masks={'skin':np.ones((8,12),np.float32),
                         'confidence':np.ones((8,12),np.float32),'protected':locked},blend=RegionBlend(1))
        output,record=self.backend.run(self.source,BUNDLE,run_id=self.run_id)
        updated=store.replace_texture(job['id'],output,expected_revision=1,candidate_recipe=record)
        self.assertEqual(updated['revision'],2)
        with store.open_array(job['id'],'master') as master:
            np.testing.assert_array_equal(master[:,:3],self.source[:,:3])
            np.testing.assert_array_equal(master[:,3:],self.output[:,3:])
        with self.assertRaises(RevisionConflict):store.replace_texture(job['id'],output,expected_revision=1,candidate_recipe=record)

    def test_validate_workflow_rejects_missing_comfy_v3_combo_choice(self):
        schema = copy.deepcopy(SCHEMA)
        schema['UpscaleModelLoader'] = {
            'input': {'required': {'model_name': ['COMBO', {'multiselect': False, 'options': ['realesr-general-x4v3.pth']}]}},
            'output': ['UPSCALE_MODEL'],
        }
        schema['ImageUpscaleWithModel'] = {
            'input': {'required': {'upscale_model': ['UPSCALE_MODEL'], 'image': ['IMAGE']}},
            'output': ['IMAGE'],
        }
        valid_bundle = {
            'schema_version': 1,
            'family': 'other',
            'input_node': '1',
            'output_node': '4',
            'workflow': {
                '1': {'class_type': 'LoadImage', 'inputs': {'image': 'placeholder.png'}},
                '2': {'class_type': 'UpscaleModelLoader', 'inputs': {'model_name': 'realesr-general-x4v3.pth'}},
                '3': {'class_type': 'ImageUpscaleWithModel', 'inputs': {'upscale_model': ['2', 0], 'image': ['1', 0]}},
                '4': {'class_type': 'SaveImage', 'inputs': {'images': ['3', 0], 'filename_prefix': 'test'}},
            },
        }
        validate_workflow(valid_bundle, schema)
        bad_bundle = copy.deepcopy(valid_bundle)
        bad_bundle['workflow']['2']['inputs']['model_name'] = 'missing_upscaler.pth'
        with self.assertRaises(ValueError):
            validate_workflow(bad_bundle, schema)

if __name__=='__main__':unittest.main()
