import http.client
import io
import json
import socket
import tempfile
import unittest
from pathlib import Path

from mobile_upload import MobileInbox, MobileUploadServer


class MobileUploadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='huihui-mobile-test-', dir=r'G:\LocalCodex-work\mycodex-repair-20261009\artifacts')
        self.root = Path(self.tmp.name)
        self.inbox = MobileInbox(self.root)
        self.server = MobileUploadServer(self.inbox, port=0)
        self.port = self.server.start()

    def tearDown(self):
        self.server.close()
        self.tmp.cleanup()

    def request(self, method, path, body=None, auth=True, headers=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=5)
        try:
            headers = dict(headers or {})
            if auth:
                headers['Authorization'] = 'Bearer ' + self.inbox.access_code
            conn.request(method, path, body=body, headers=headers)
            response = conn.getresponse()
            data = response.read()
            return response.status, data, dict(response.getheaders())
        finally:
            conn.close()

    def test_pwa_static_and_auth(self):
        status, page, headers = self.request('GET', '/', auth=False)
        self.assertEqual(status, 200)
        self.assertIn(b'Huihui', page)
        self.assertIn(b'id=\"reasoningEffort\"', page)
        self.assertIn(b'value=\"low\"', page)
        self.assertIn(b'value=\"medium\" selected', page)
        self.assertIn(b'value=\"xhigh\"', page)
        self.assertIn('Content-Security-Policy', headers)
        status, worker, _ = self.request('GET','/sw.js',auth=False)
        self.assertEqual(status,200)
        self.assertIn(b'huihui-mobile-v56',worker)
        status, data, _ = self.request('GET', '/api/jobs', auth=False)
        self.assertEqual(status, 401)
        self.assertNotIn(self.inbox.access_code.encode(), data)

    def test_upload_queue_claim_cancel_and_safe_status(self):
        status, data, _ = self.request('POST', '/api/jobs', json.dumps({'task':'file cleanup'}),
            headers={'Content-Type':'application/json'})
        self.assertEqual(status, 201)
        job_id = json.loads(data)['id']
        payload = b'hello test file'
        status, data, _ = self.request('PUT', f'/api/jobs/{job_id}/files/a.txt', payload,
            headers={'Content-Length':str(len(payload)), 'Content-Type':'application/octet-stream'})
        self.assertEqual(status, 201)
        self.assertEqual((self.root / 'jobs' / job_id / 'uploads' / 'a.txt').read_bytes(), payload)
        status, data, _ = self.request('POST', f'/api/jobs/{job_id}/submit', b'{}',
            headers={'Content-Type':'application/json'})
        self.assertEqual(status, 200)
        self.assertEqual(self.inbox.get(job_id)['status'], 'queued')
        row = self.inbox.claim_next()
        self.assertEqual(row['id'], job_id)
        self.assertEqual(row['status'], 'processing')
        self.inbox.cancel(job_id)
        self.assertTrue(self.inbox.get(job_id)['cancel_requested'])
        self.inbox.update(job_id, status='completed', result='done')
        status, data, _ = self.request('GET', f'/api/jobs/{job_id}')
        self.assertEqual(status, 200)
        view = json.loads(data)
        self.assertEqual(view['result'], 'done')
        self.assertEqual(view['files'], ['a.txt'])
        self.assertNotIn('workspace', view)
        self.assertNotIn('path', view)

    def test_phone_reasoning_effort_roundtrip_and_validation(self):
        for effort in ('low','medium','xhigh'):
            status, data, _ = self.request('POST','/api/jobs',
                json.dumps({'task':'mode roundtrip','reasoning_effort':effort}),
                headers={'Content-Type':'application/json'})
            self.assertEqual(status,201)
            job_id=json.loads(data)['id']
            self.assertEqual(json.loads(data)['reasoning_effort'],effort)
            self.assertEqual(self.inbox.get(job_id)['reasoning_effort'],effort)
            status,data,_=self.request('GET',f'/api/jobs/{job_id}')
            self.assertEqual(status,200)
            self.assertEqual(json.loads(data)['reasoning_effort'],effort)
        status,data,_=self.request('POST','/api/jobs',
            json.dumps({'task':'bad mode','reasoning_effort':'secret'}),
            headers={'Content-Type':'application/json'})
        self.assertEqual(status,400)
        self.assertIn('思考模式',json.loads(data)['error'])

    def test_phone_reasoning_effort_defaults_to_medium_for_older_clients(self):
        row=self.inbox.create('legacy mobile client')
        self.assertEqual(row['reasoning_effort'],'medium')

    def test_rejects_executable_and_missing_upload_length(self):
        row = self.inbox.create('blocked extension test')
        payload=b'x'
        status, _, _ = self.request('PUT', f"/api/jobs/{row['id']}/files/setup.exe", payload,
            headers={'Content-Length':'1'})
        self.assertEqual(status, 400)
        request=(f"PUT /api/jobs/{row['id']}/files/no-length.txt HTTP/1.1\r\n"
                 f"Host: 127.0.0.1:{self.port}\r\nAuthorization: Bearer {self.inbox.access_code}\r\n"
                 "Connection: close\r\n\r\n").encode('ascii')
        with socket.create_connection(('127.0.0.1',self.port),timeout=5) as sock:
            sock.sendall(request)
            response=sock.recv(4096)
        self.assertIn(b'411',response)
        self.assertEqual(self.inbox.get(row['id'])['files'], [])

    def test_interrupted_upload_leaves_no_partial_file(self):
        row = self.inbox.create('interrupted upload')
        with self.assertRaises(ValueError):
            self.inbox.add_file(row['id'], 'broken.txt', io.BytesIO(b'abc'), 10)
        uploads = self.root / 'jobs' / row['id'] / 'uploads'
        self.assertEqual(list(uploads.iterdir()), [])
        self.assertEqual(self.inbox.get(row['id'])['files'], [])

    def test_restart_requires_review_and_never_requeues(self):
        row=self.inbox.create('restart test')
        self.inbox.update(row['id'], status='processing')
        self.inbox.recover_interrupted()
        recovered=self.inbox.get(row['id'])
        self.assertEqual(recovered['status'], 'needs_review')
        self.assertIsNone(self.inbox.claim_next())
        self.assertIn(chr(0x68c0), recovered['progress'])

    def test_invalid_job_id_cannot_escape_storage_root(self):
        with self.assertRaises(ValueError):
            self.inbox.add_file('../escape', 'x.txt', io.BytesIO(b'x'), 1)
        self.assertFalse((self.root.parent / 'escape').exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)
