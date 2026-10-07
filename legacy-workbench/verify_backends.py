"""Regress backend selection and safe switching without real inference."""
from contextlib import ExitStack
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

import core


SETTINGS = {'model': core.MODEL, 'backend': 'hip', 'model_contexts': {core.MODEL: 256000},
            'kv_cache_location': 'auto', 'cpu_offload': False, 'api_key': 'test-only'}
LIVE = {'model': core.MODEL, 'backend': 'hip', 'context': 109568,
        'context_limit': 256000, 'gpu_layers': 'all', 'reasoning_budget': -1, 'kv_cache_location': 'gpu'}


class BackendChecks(unittest.TestCase):
    def test_each_backend_keeps_gpu_weights_and_unrestricted_reasoning(self):
        for backend, device in (('hip', 'ROCm0'), ('vulkan', 'Vulkan0')):
            with patch.object(core, 'load_settings', return_value={**SETTINGS, 'backend': backend}):
                args = core.model_args(core.MODEL, 109568)
            self.assertEqual(Path(args[0]), core.runtime_executable(backend))
            self.assertEqual(args[args.index('--device')+1], device)
            self.assertEqual(args[args.index('-ngl')+1], 'all')
            self.assertEqual(args[args.index('--reasoning-budget')+1], '-1')
            self.assertEqual(args[args.index('-n')+1], '-1')
            self.assertIn('--kv-offload', args)

    def test_reuse_requires_matching_backend_and_old_metadata_means_vulkan(self):
        self.assertTrue(core.runtime_matches_settings(LIVE, SETTINGS))
        self.assertFalse(core.runtime_matches_settings({**LIVE, 'backend': 'vulkan'}, SETTINGS))
        old = {key: value for key, value in LIVE.items() if key != 'backend'}
        self.assertTrue(core.runtime_matches_settings(old, {**SETTINGS, 'backend': 'vulkan'}))
        self.assertFalse(core.runtime_matches_settings(old, SETTINGS))

    def test_probe_uses_selected_executable_and_reports_device_memory(self):
        with patch.object(core, 'load_settings', return_value=SETTINGS), \
             patch.object(core, 'ensure_backend_installed'), \
             patch.object(core.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0,
                 b'Available devices:\n ROCm0: AMD Radeon RX 9070 (16368 MiB, 15000 MiB free)\n', b'')) as run:
            self.assertEqual(core.gpu_device_memory(), (16368, 15000))
        self.assertEqual(run.call_args.args[0][0], str(core.runtime_executable('hip')))
        self.assertEqual(run.call_args.kwargs['cwd'], core.runtime_directory('hip'))

    def test_no_gpu_probe_is_explicit_error_not_cpu_fallback(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(core, 'ROOT', Path(directory)), \
             patch.object(core, 'load_settings', return_value=SETTINGS), \
             patch.object(core, 'ensure_backend_installed'), \
             patch.object(core.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, b'(none)', b'')):
            (Path(directory)/'logs').mkdir()
            with self.assertRaisesRegex(RuntimeError, 'CPU'):
                core.gpu_device_memory()

    def test_private_library_search_path_does_not_modify_process_environment(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(core, 'ROOT', Path(directory)):
            math = Path(directory)/'runtime-hip/sdk/libraries/bin'
            math.mkdir(parents=True)
            (math/'hipblas.dll').write_bytes(b'test')
            previous = dict(os.environ)
            env = core.runtime_environment('hip')
            self.assertIn(str(math), env['PATH'])
            self.assertEqual(dict(os.environ), previous)
            self.assertEqual(core.runtime_environment('vulkan'), previous)

    def test_missing_backend_does_not_stop_running_vulkan(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(core, 'ROOT', Path(directory)), \
             patch.object(core, 'load_settings', return_value=SETTINGS), \
             patch.object(core, '_stop_model') as stop:
            with self.assertRaisesRegex(RuntimeError, '未安装'):
                core._start_model(core.MODEL, 109568, False, 256000)
            stop.assert_not_called()

    def test_switch_stops_owned_old_runtime_and_launches_selected_backend(self):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            root = Path(directory)
            stack.enter_context(patch.object(core, 'ROOT', root))
            (root/'logs').mkdir()
            for backend in core.BACKENDS:
                core.runtime_directory(backend).mkdir()
                core.runtime_executable(backend).write_bytes(b'test')
            model = root/'model.gguf'; model.write_bytes(b'test')
            image = root/'vision.gguf'; image.write_bytes(b'test')
            stack.enter_context(patch.object(core, 'model_file', return_value=model))
            stack.enter_context(patch.object(core, 'VISION_FILE', image))
            stack.enter_context(patch.object(core, 'load_settings', return_value=SETTINGS))
            stack.enter_context(patch.object(core, 'active_model', return_value={**LIVE, 'backend': 'vulkan'}))
            stack.enter_context(patch.object(core, 'server_ready', side_effect=[True, True, False]))
            stack.enter_context(patch.object(core, 'api', side_effect=lambda route: (
                {'model_path': str(model), 'default_generation_settings': {'n_ctx': 109568}}
                if route == '/props' else [])))
            stack.enter_context(patch.object(core, 'ensure_full_gpu_capacity'))
            stop = stack.enter_context(patch.object(core, '_stop_model'))
            launch = stack.enter_context(patch.object(core.subprocess, 'Popen', return_value=Mock(pid=42)))
            core._start_model(core.MODEL, 109568, False, 256000)
            stop.assert_called_once()
            self.assertEqual(launch.call_args.args[0][0], str(core.runtime_executable('hip')))
            record = json.loads((root/'active-model.json').read_text())
            self.assertEqual(record['backend'], 'hip')
            self.assertEqual(record['context_limit'], 256000)


if __name__ == '__main__':
    unittest.main(verbosity=2)
