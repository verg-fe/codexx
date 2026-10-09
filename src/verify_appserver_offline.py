"""Real app-server initialize with an intentionally unavailable VLESS tunnel."""
from pathlib import Path
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

import core


class AppServerOfflineCheck(unittest.TestCase):
    def test_local_codex_app_server_initializes_when_proxy_fails(self):
        engine_source=Path(r'D:\LocalCodex\engine')
        self.assertTrue((engine_source/'codex.exe').is_file())
        work=Path(r'G:\LocalCodex-work\mycodex-repair-20261009\artifacts\temp')
        work.mkdir(parents=True,exist_ok=True)
        # Windows may retain the just-closed engine log briefly; the test
        # outcome is the initialize/EOF handshake, not immediate deletion.
        with tempfile.TemporaryDirectory(prefix='appserver-smoke-',dir=work,
                                         ignore_cleanup_errors=True) as temp:
            root=Path(temp)
            shutil.copytree(engine_source,root/'engine')
            home=root/'codex-home';home.mkdir()
            (root/'logs').mkdir()
            (home/'config.toml').write_text('''
model = "offline-smoke"
model_provider = "local"
model_context_window = 8192
approval_policy = "never"
sandbox_mode = "unelevated"
[model_providers.local]
name = "local smoke test"
base_url = "http://127.0.0.1:8081/v1"
wire_api = "responses"
experimental_bearer_token = "offline-smoke-token"
requires_openai_auth = false
''',encoding='utf-8')
            (root/'proxy-settings.json').write_text('{"enabled":true}',encoding='utf-8')
            with patch.object(core,'ROOT',root), \
                 patch('proxy_service.ProxyLease.start',side_effect=RuntimeError('intentional test tunnel failure')):
                client=core.RpcClient(lambda event: None)
                try:
                    self.assertIsNone(client.process.poll())
                    self.assertEqual(client.proxy_error,'intentional test tunnel failure')
                finally:
                    client.close()
                self.assertIsNotNone(client.process.poll())


if __name__=='__main__':
    unittest.main(verbosity=2)
