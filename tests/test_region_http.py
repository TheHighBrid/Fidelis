"""Real HTTP import, restart, reblend, export and request-isolation tests."""
import base64
import io
import json
import threading
from types import SimpleNamespace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import tempfile
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import zipfile

import numpy as np
from PIL import Image

from fidelis.studio.http import _local_request, _masks, dispatch
from fidelis.studio.store import JobStore


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = self.temp.name
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                dispatch(self, root)
            def do_POST(self):
                dispatch(self, root)
            def log_message(self, *args):
                pass
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop)
        self.url = 'http://127.0.0.1:' + str(self.server.server_port)
        self.base = np.random.default_rng(6).integers(0, 256, (8, 12, 3), dtype=np.uint8)
        self.texture = 255 - self.base
        self.masks = dict(skin=np.ones((8,12), np.float32),
                          confidence=np.ones((8,12), np.float32),
                          protected=np.pad(np.ones((8,4), np.float32), ((0,0),(0,8))))

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def request(self, path, payload=None, headers=None):
        req = Request(self.url+path, data=None if payload is None else json.dumps(payload).encode(),
                      headers={'Content-Type':'application/json', **(headers or {})})
        with urlopen(req, timeout=5) as response:
            return response.status, response.read(), response.headers

    def create(self, profile='luxury_apparel', with_masks=True):
        def encoded_image(arr):
            stream = io.BytesIO()
            Image.fromarray(arr).save(stream, format='PNG')
            return base64.b64encode(stream.getvalue()).decode()
        stream = io.BytesIO()
        np.savez_compressed(stream, **self.masks)
        payload = dict(base=encoded_image(self.base), texture=encoded_image(self.texture),
                       masks=base64.b64encode(stream.getvalue()).decode(), profile=profile, label='Test job')
        if not with_masks:
            del payload['masks']
        status, body, _ = self.request('/api/regions/jobs', payload)
        self.assertEqual(status, 201)
        return json.loads(body)

    def test_import_reopen_reblend_export_and_stale_write(self):
        job = self.create()
        # Simulate the app restarting: a new store instance must use disk state.
        self.server.region_store = JobStore(self.temp.name)
        self.assertEqual(json.loads(self.request('/api/regions/jobs')[1])['jobs'][0]['id'], job['id'])
        path = '/api/regions/jobs/'+job['id']
        blend = dict(skin=.9, hair=.2, fabric=.15, edge_protection=0)
        updated = json.loads(self.request(path+'/reblend', {'blend':blend,'expected_revision':1})[1])
        self.assertEqual(updated['revision'],2)
        with self.assertRaises(HTTPError) as caught:
            self.request(path+'/reblend', {'blend':blend,'expected_revision':1})
        self.assertEqual(caught.exception.code,409)
        _, encoded, headers = self.request(path+'/export')
        self.assertIn('attachment', headers['Content-Disposition'])
        with Image.open(io.BytesIO(encoded)) as image:
            self.assertEqual(image.size,(12,8))
            np.testing.assert_array_equal(np.array(image)[:,:4],self.base[:,:4])
        self.assertIn(b'Regional Review', self.request('/regions')[1])
        self.assertEqual(self.request(path+'/delete',{})[0],200)
        self.assertEqual(json.loads(self.request('/api/regions/jobs')[1])['jobs'],[])

    def test_structural_crop_lock_preserves_pixels_and_rejects_stale_revision(self):
        job = self.create()
        path = "/api/regions/jobs/" + job["id"]
        payload = {"regions": [[5, 1, 3, 4]], "expected_revision": 1, "target": "master"}
        _, body, _ = self.request(path + "/inspect-structure", payload)
        self.assertGreater(json.loads(body)["regions"][0]["changed_pixels"], 0)

        with self.assertRaises(HTTPError) as caught:
            self.request(path + "/lock-structure", {**payload, "regions": [[11, 1, 2, 4]]})
        self.assertEqual(caught.exception.code, 400)
        _, body, _ = self.request(path + "/lock-structure", payload)
        result = json.loads(body)
        self.assertEqual(result["revision"], 2)
        self.assertEqual(result["blend"], job["blend"])

        with self.assertRaises(HTTPError) as caught:
            self.request(path + "/lock-structure", payload)
        self.assertEqual(caught.exception.code, 409)

        _, body, _ = self.request(path + "/inspect-structure", {**payload, "expected_revision": 2})
        self.assertEqual(json.loads(body)["regions"][0]["changed_pixels"], 0)
        _, encoded, _ = self.request(path + "/export?revision=2")
        with Image.open(io.BytesIO(encoded)) as image:
            master = np.array(image)
        np.testing.assert_array_equal(master[1:5, 5:8], self.base[1:5, 5:8])
        np.testing.assert_array_equal(master[:, :4], self.base[:, :4])
        self.assertTrue(np.any(master[:, 8:] != self.base[:, 8:]))

    def test_paint_from_scratch_save_reopen_and_mask_data(self):
        job = self.create(with_masks=False)
        path = '/api/regions/jobs/'+job['id']
        with Image.open(io.BytesIO(self.request(path+'/export')[1])) as image:
            np.testing.assert_array_equal(np.array(image),self.base)
        stroke = {'layer':'fabric','mode':'paint','radius':.4,'opacity':1,'hardness':1,
                  'points':[[.3,.5],[.8,.5]]}
        updated=json.loads(self.request(path+'/reblend', {'expected_revision':1,
                          'blend':{'fabric':1,'skin':0,'hair':0},'strokes':[stroke]})[1])
        self.assertEqual(updated['revision'],2)
        masks=json.loads(self.request(path+'/mask-data?revision=2')[1])
        fabric=np.frombuffer(base64.b64decode(masks['layers']['fabric']),dtype=np.uint8)
        self.assertEqual(int(fabric.max()),255)
        self.server.region_store=JobStore(self.temp.name)
        self.assertEqual(json.loads(self.request(path)[1])['last_mask_edit']['strokes'][0]['layer'],'fabric')
        with self.assertRaises(HTTPError) as caught:
            self.request(path+'/mask-data?revision=1')
        self.assertEqual(caught.exception.code,409)
        self.assertIn(b'MaskHistory',self.request('/api/regions/editor.js')[1])

    def test_cross_origin_and_dns_rebinding_rejected(self):
        with self.assertRaises(PermissionError):
            _local_request(SimpleNamespace(client_address=("203.0.113.9", 1000),
                                           headers={"Host": "localhost"}))
        for headers in ({'Origin':'https://evil.example'}, {'Host':'evil.example'}):
            with self.assertRaises(HTTPError) as caught:
                self.request('/api/regions/jobs',headers=headers)
            self.assertEqual(caught.exception.code,403)

    def test_strict_profile_rejects_generated_blend(self):
        job = self.create('packshot_strict')
        with self.assertRaises(HTTPError) as caught:
            self.request('/api/regions/jobs/'+job['id']+'/reblend',
                         {'expected_revision':1,'blend':{'skin':1}})
        self.assertEqual(caught.exception.code,400)
        with Image.open(io.BytesIO(self.request('/api/regions/jobs/'+job['id']+'/export')[1])) as image:
            np.testing.assert_array_equal(np.array(image),self.base)

    def test_forged_large_npy_header_rejected_before_loading(self):
        header = io.BytesIO()
        np.lib.format.write_array_header_1_0(header, {'descr':'<f4','fortran_order':False,
                                                     'shape':(10**9,10**9)})
        archive = io.BytesIO()
        with zipfile.ZipFile(archive,'w') as stream:
            stream.writestr('confidence.npy',header.getvalue())
        with self.assertRaisesRegex(ValueError,'contract'):
            _masks(base64.b64encode(archive.getvalue()).decode(),(8,12))

    def test_invalid_requests_do_not_create_jobs(self):
        for data in ({}, {'base':'corrupt','texture':'corrupt','masks':'corrupt'}):
            with self.assertRaises(HTTPError):
                self.request('/api/regions/jobs',data)
        self.assertEqual(json.loads(self.request('/api/regions/jobs')[1])['jobs'],[])


if __name__ == '__main__':
    unittest.main()
