"""Regression for Windows status-file locks aborting otherwise valid inference."""
import concurrent.futures
from contextlib import contextmanager
import ctypes
import http.client
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

import gateway

ARTIFACTS = Path(r'G:\LocalCodex-work\mycodex-repair-20261009\artifacts')


@contextmanager
def deny_delete(path):
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32,
        ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32,
        ctypes.c_void_p]
    kernel.CreateFileW.restype = ctypes.c_void_p
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.CreateFileW(str(path), 0x80000000, 1, None, 3, 128, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        yield
    finally:
        kernel.CloseHandle(handle)


class StatusWriteRegression(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(dir=ARTIFACTS)
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.path = self.root / 'request-routing.json'

    def test_concurrent_writers_publish_valid_json_and_clean_temporary_files(self):
        def write(number):
            return gateway.write_status_json(self.path, {'request': number, 'text': '中文'})
        with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
            self.assertTrue(all(pool.map(write, range(60))))
        result = json.loads(self.path.read_text(encoding='utf-8'))
        self.assertIn(result['request'], range(60))
        self.assertEqual(result['text'], '中文')
        self.assertEqual(list(self.root.glob('*.tmp')), [])

    def test_transient_sharing_violation_is_retried(self):
        original = gateway.os.replace
        calls = []
        def replace(source, destination):
            calls.append(source)
            if len(calls) < 3:
                raise PermissionError('fixture sharing violation')
            return original(source, destination)
        with patch.object(gateway.os, 'replace', side_effect=replace), \
             patch.object(gateway.time, 'sleep'):
            self.assertTrue(gateway.write_status_json(self.path, {'ready': True}))
        self.assertEqual(len(calls), 3)
        self.assertEqual(json.loads(self.path.read_text()), {'ready': True})

    @unittest.skipUnless(os.name == 'nt', 'Windows sharing semantics')
    def test_real_windows_lock_preserves_previous_record(self):
        self.path.write_text('{"previous": true}', encoding='utf-8')
        with deny_delete(self.path):
            self.assertFalse(gateway.write_status_json(self.path, {'new': True}))
        self.assertEqual(json.loads(self.path.read_text()), {'previous': True})
        self.assertEqual(list(self.root.glob('*.tmp')), [])
        self.assertTrue(gateway.write_status_json(self.path, {'recovered': True}))

    def test_unwritable_directory_is_nonfatal(self):
        with patch.object(gateway.tempfile, 'NamedTemporaryFile',
                          side_effect=PermissionError('fixture directory denied')):
            self.assertFalse(gateway.write_status_json(self.path, {'ready': True}))

    @unittest.skipUnless(os.name == 'nt', 'Windows sharing semantics')
    def test_real_locked_routing_record_does_not_abort_model_routing(self):
        self.path.write_text('{"previous": true}', encoding='utf-8')
        with deny_delete(self.path), \
             patch.object(gateway, 'ROOT', self.root), \
             patch.object(gateway, 'context_for', return_value=93000), \
             patch.object(gateway, 'start_model') as start, \
             patch.object(gateway, 'request_output_reserve', return_value=16), \
             patch.object(gateway, 'count_prompt_tokens', return_value=100), \
             patch.object(gateway, 'runtime_context_for', return_value=93000), \
             patch.object(gateway, 'fit_generation_to_window', return_value={}), \
             patch.object(gateway, 'active_model', return_value={'context': 93000}), \
             patch.object(gateway, 'archive_thread_id', return_value=None), \
             patch.object(gateway, 'reasoning_budget', return_value=128):
            result = gateway.route_inference({}, '/v1/chat/completions', {}, 'fixture')
        self.assertEqual(result['phase'], 'ready')
        self.assertEqual(start.call_count, 2)
        self.assertEqual(json.loads(self.path.read_text()), {'previous': True})

    def test_genuine_upstream_failure_returns_utf8_json_over_http(self):
        settings = {'api_key': 'fixture-only'}
        class QuietHandler(gateway.Handler):
            def log_message(self, *args):
                pass
        with patch.object(gateway, 'load_settings', return_value=settings), \
             patch.object(gateway, 'MODELS', {'fixture': {}}), \
             patch.object(gateway, 'guard_options', return_value={'output_tokens': 16}), \
             patch.object(gateway, 'model_supports_vision', return_value=True), \
             patch.object(gateway, 'reasoning_budget', return_value=128), \
             patch.object(gateway, 'route_inference', side_effect=RuntimeError('拒绝访问：测试')):
            server = gateway.LocalServer(('127.0.0.1', 0), QuietHandler)
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            try:
                client = http.client.HTTPConnection(*server.server_address, timeout=5)
                client.request('POST', '/v1/chat/completions',
                    json.dumps({'model': 'fixture', 'messages': []}),
                    {'Authorization': 'Bearer fixture-only', 'Content-Type': 'application/json'})
                response = client.getresponse()
                result = json.loads(response.read().decode('utf-8'))
                self.assertEqual(response.status, 503)
                self.assertIn('application/json', response.getheader('Content-Type'))
                self.assertEqual(result['error']['message'], '拒绝访问：测试')
                self.assertEqual(result['error']['code'], 'local_gateway_unavailable')
                client.close()
            finally:
                server.shutdown()
                server.server_close()
                worker.join(timeout=5)


if __name__ == '__main__':
    unittest.main(verbosity=2)
