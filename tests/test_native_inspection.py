"""Native crop pixel, protocol and client sequencing contracts, not model quality."""
import io
import json
from pathlib import Path
import shutil
import subprocess
import unittest
from urllib.error import HTTPError
from urllib.parse import urlencode

import numpy as np
from PIL import Image

import test_region_http as http_fixture
from fidelis.postprocess.regions import RegionBlend
from fidelis.studio.inspection import crop_bounds, native_crop
from fidelis.studio.store import JobStore


class NativeInspectionTests(unittest.TestCase):
    def setUp(self):
        self.fixture=http_fixture.HttpTests('test_import_reopen_reblend_export_and_stale_write')
        self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.store=JobStore(self.fixture.temp.name)
        self.fixture.server.region_store=self.store

    def create(self,base=None):
        base=self.fixture.base if base is None else base
        texture=255-base
        confidence=np.ones(base.shape[:2],np.float32)
        protected=np.zeros(base.shape[:2],np.float32);protected[:,:3]=1
        return self.store.create(base,texture,masks={'skin':confidence,'confidence':confidence,
                     'protected':protected},blend=RegionBlend(skin=1,edge_protection=0))

    def crop(self,job,role='master',**params):
        query={'role':role,'revision':job['revision'],'x':1,'y':2,'width':5,'height':4,**params}
        return self.fixture.request('/api/regions/jobs/'+job['id']+'/crop?'+urlencode(query))

    def decode(self,response):
        with Image.open(io.BytesIO(response[1])) as image:return np.array(image)

    def test_exact_same_grid_base_texture_and_protected_master(self):
        job=self.create()
        for role in ('base','texture','master'):
            response=self.crop(job,role)
            self.assertEqual(response[0],200)
            self.assertEqual(response[2]['X-Fidelis-Revision'],'1')
            self.assertEqual(response[2]['X-Fidelis-Crop'],'1,2,5,4')
            self.assertEqual(response[2]['Cache-Control'],'no-store')
            with self.store.open_array(job['id'],role) as full:
                np.testing.assert_array_equal(self.decode(response),full[2:6,1:6])
        base=self.decode(self.crop(job,'base'));master=self.decode(self.crop(job))
        np.testing.assert_array_equal(master[:,:2],base[:,:2])
        np.testing.assert_array_equal(master[:,2:],255-base[:,2:])

    def test_native_crop_is_not_preview_upscaling_on_odd_large_image(self):
        y,x=np.indices((1001,1203));base=np.stack((x%256,y%256,(x+y)%256),axis=-1).astype(np.uint8)
        job=self.create(base)
        preview=self.fixture.request(f"/api/regions/jobs/{job['id']}/preview?role=base&revision=1")
        self.assertEqual(self.decode(preview).shape,(501,602,3))
        native=self.decode(self.crop(job,'base',x=1001,y=797,width=127,height=129))
        self.assertEqual(native.shape,(129,127,3))
        np.testing.assert_array_equal(native,base[797:926,1001:1128])
        self.assertNotEqual(int(native[0,0,0]),int(native[0,1,0]))
        self.assertNotEqual(int(native[0,0,1]),int(native[1,0,1]))

    def test_edges_one_pixel_and_last_corner_without_padding(self):
        job=self.create();base=self.fixture.base
        native=self.decode(self.crop(job,'base',x=11,y=7,width=1,height=1))
        np.testing.assert_array_equal(native,base[7:8,11:12])
        np.testing.assert_array_equal(self.decode(self.crop(job,'base',x=0,y=0,width=12,height=8)),base)

    def test_invalid_rectangles_roles_and_revision_are_rejected(self):
        job=self.create()
        invalid=[dict(x=-1),dict(y=-1),dict(width=0),dict(height=0),dict(width=513),dict(height=513),
                 dict(x=12),dict(y=8),dict(x=9,width=4),dict(y=6,height=3),dict(x='1.5'),
                 dict(x='nan'),dict(width='inf'),dict(revision=0),dict(role='protected'),dict(role='../../base')]
        for params in invalid:
            role=params.pop('role','master')
            with self.subTest(params=params,role=role),self.assertRaises(HTTPError) as caught:
                self.crop(job,role,**params)
            self.assertEqual(caught.exception.code,400)
        root=f"/api/regions/jobs/{job['id']}/crop?"
        for query in ('role=base','role=base&revision=1&x=0&y=0&width=1&height=1&x=1',
                      'role=base&revision=1&x=0&y=0&width=1&height=1&extra=1'):
            with self.assertRaises(HTTPError) as caught:self.fixture.request(root+query)
            self.assertEqual(caught.exception.code,400)

    def test_stale_pair_is_refused_instead_of_mixing_revisions(self):
        job=self.create()
        self.crop(job,'base')
        self.store.reblend(job['id'],expected_revision=1,blend=RegionBlend(skin=.2))
        with self.assertRaises(HTTPError) as caught:self.crop(job,'master')
        self.assertEqual(caught.exception.code,409)
        current=self.store.get(job['id']);self.assertEqual(self.crop(current)[0],200)

    def test_read_only_crop_does_not_modify_saved_job(self):
        job=self.create();before=self.store.get(job['id'])
        self.crop(job,'base');self.crop(job,'master')
        self.assertEqual(before,self.store.get(job['id']))
        self.store.delete(job['id'])
        with self.assertRaises(HTTPError) as caught:self.crop(job)
        self.assertEqual(caught.exception.code,404)

    def test_crop_preserves_origin_restrictions_and_script_is_served(self):
        job=self.create()
        query='role=base&revision=1&x=0&y=0&width=1&height=1'
        with self.assertRaises(HTTPError) as caught:
            self.fixture.request(f"/api/regions/jobs/{job['id']}/crop?{query}",headers={'Origin':'http://untrusted'})
        self.assertEqual(caught.exception.code,403)
        response=self.fixture.request('/api/regions/inspection.js')
        self.assertIn(b'PairLoader',response[1])
        self.assertIn('javascript',response[2]['Content-Type'])

    def test_numpy_slice_validation_and_independent_copy(self):
        a=np.zeros((8,12,3),np.uint8)
        crop=native_crop(a,x=0,y=0,width=2,height=2);crop[:]=5
        self.assertFalse(np.any(a))
        for value in (True,1.5,'1',np.int64(1)):
            with self.assertRaises(ValueError):crop_bounds(a.shape,x=value,y=0,width=1,height=1)

    def test_actual_editor_dom_inspection_preserves_unsaved_state(self):
        node=shutil.which('node')
        if not node:self.skipTest('Node unavailable: DOM contract not verified')
        root=Path(__file__).resolve().parents[1]
        result=subprocess.run([node,str(root/'tests/native-inspection-ui.cjs'),str(root/'fidelis/studio/studio.html')],
                              capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_client_geometry_css_scale_and_stale_pair_loading(self):
        node=shutil.which('node')
        if not node:self.skipTest('Node unavailable: client geometry/sequencing not verified')
        module=Path(__file__).resolve().parents[1]/'fidelis/studio/inspection.js'
        source=r'''
const assert=require('node:assert/strict');const m=require(process.argv[1]);
(async()=>{
 assert.deepEqual(m.rectangle([8001,6003],[7999,6002],512),{x:7489,y:5491,width:512,height:512});
 assert.deepEqual(m.rectangle([7,5],[0,0],256),{x:0,y:0,width:7,height:5});
 assert.deepEqual(m.previewPoint([8001,6003],{left:10,top:20,width:800,height:600},810,620),[8000,6002]);
 assert.deepEqual(m.previewPoint([8001,6003],{left:10,top:20,width:800,height:600},410,320),[4000,3001]);
 assert.deepEqual(m.cssSize({width:127,height:129},1),{width:127,height:129});
 assert.deepEqual(m.cssSize({width:127,height:129},2),{width:254,height:258});
 assert.throws(()=>m.cssSize({width:1,height:1},.5));
 assert.throws(()=>m.rectangle([8001,6003],[-1,0],256));
 assert.throws(()=>m.rectangle([8001,6003],[1.5,0],256));
 const job={id:'job',revision:7,dimensions:[8001,6003]},rect=m.rectangle(job.dimensions,[2500,2000],256);
 const paths=m.urls(job,rect,'texture').map(path=>new URL(path,'http://localhost'));
 for(const key of ['revision','x','y','width','height'])assert.equal(paths[0].searchParams.get(key),paths[1].searchParams.get(key));
 assert.equal(paths[0].searchParams.get('role'),'base');assert.equal(paths[1].searchParams.get('role'),'texture');
 let committed=[],errors=[],pending=[],loader=new m.PairLoader();
 const image={naturalWidth:256,naturalHeight:256};
 const first=loader.load(job,[2500,2000],256,'master',()=>new Promise(resolve=>pending.push(resolve)),value=>committed.push(value),e=>errors.push(e));
 assert.equal(committed.length,0);
 pending[0](image);await Promise.resolve();assert.equal(committed.length,0);
 await loader.load(job,[3500,3000],256,'texture',async()=>image,value=>committed.push(value),e=>errors.push(e));
 pending[1](image);await first;assert.equal(committed.length,1);assert.equal(committed[0].role,'texture');assert.equal(committed[0].rect.x,3372);
 await loader.load(job,[0,0],256,'master',async()=>({naturalWidth:1,naturalHeight:1}),value=>committed.push(value),e=>errors.push(e));
 assert.equal(errors.length,1);assert.equal(committed.length,1);
 await loader.load(job,[0,0],256,'master',async()=>{throw new Error('409 stale')},value=>committed.push(value),e=>errors.push(e));
 assert.equal(errors.length,2);
 pending=[];
 const cancelled=loader.load(job,[0,0],256,'master',()=>new Promise(resolve=>pending.push(resolve)),value=>committed.push(value),e=>errors.push(e));
 loader.invalidate();pending.forEach(resolve=>resolve(image));await cancelled;assert.equal(committed.length,1);
 console.log('Native geometry, CSS scale, paired readiness and stale-load contracts passed.');
})().catch(error=>{console.error(error);process.exitCode=1});
'''
        result=subprocess.run([node,'-e',source,str(module)],capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)


if __name__=='__main__':unittest.main()
