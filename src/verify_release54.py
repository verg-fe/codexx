"""Regression tests for defects found independently during v53 acceptance."""
import json
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
import sqlite3
from contextlib import contextmanager
from unittest.mock import patch

import local_mcp_servers as local
import model_validation as validation
import process_identity
from tool_results import classify_output
from execution_memory import ExecutionJournal
from design_analysis_mcp import stl_inspect
from model_catalog import ModelCatalog
import trimesh


class RepairChecks(unittest.TestCase):
    def test_archive_keeps_zero_exit_build_failure_until_clean_retry(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            class Memory:
                @contextmanager
                def connect(self):
                    db = sqlite3.connect(root / 'journal.sqlite')
                    db.row_factory = sqlite3.Row
                    try:
                        with db: yield db
                    finally: db.close()
                def validate_thread(self, value): return value
                def find_rollout(self, value): return root / 'rollout.jsonl'
                def safe_source(self, path, kind): return path
                def record_id(self, path, offset): return offset
            path = root / 'rollout.jsonl'
            rows = [{'type': 'event_msg', 'payload': {'type': 'task_started', 'turn_id': 'turn1'}}]
            def append_attempt(call_id, output):
                rows.extend([
                    {'type': 'response_item', 'payload': {'type': 'function_call', 'call_id': call_id,
                     'name': 'exec_command', 'arguments': json.dumps({'cmd': 'build fixture'})}},
                    {'type': 'response_item', 'payload': {'type': 'function_call_output', 'call_id': call_id,
                     'output': json.dumps({'exit_code': 0, 'stdout': output})}}])
                path.write_text(''.join(json.dumps(row) + '\n' for row in rows), encoding='utf-8')
            append_attempt('a', 'Main.java:96: error: missing semicolon\nBUILD SUCCESSFUL')
            journal = ExecutionJournal(Memory())
            snapshot = journal.snapshot('fixture')
            self.assertEqual(len(snapshot['failures']), 1)
            self.assertEqual(snapshot['recent_successes'], [])
            self.assertEqual(len(journal.snapshot('fixture')['failures']), 1)
            append_attempt('b', 'mode=ic ok=0 err=28')
            self.assertEqual(len(journal.snapshot('fixture')['failures']), 2)
            append_attempt('c', 'BUILD SUCCESSFUL')
            self.assertEqual(journal.snapshot('fixture')['failures'], [])

    def test_build_error_wins_over_false_success_and_zero_exit(self):
        result = classify_output({'exit_code': 0, 'stdout':
            'Main.java:96: error: missing semicolon\r\r\nBUILD SUCCESSFUL'})
        self.assertEqual(result['execution_status'], 'succeeded')
        self.assertEqual(result['target_validation'], 'reported_failure')
        self.assertTrue(any(row.get('line') == 96 for row in result['diagnostic_findings']))

    def test_all_failed_probe_is_not_successful_target(self):
        result = classify_output({'exit_code': 0, 'stdout': 'mode=ic ok=0 err=28'})
        self.assertEqual(result['target_validation'], 'reported_failure')

    def test_pasted_powershell_missing_path_is_retained(self):
        result = classify_output({'exit_code': 0, 'stdout':
            "Get-Item:\r\r\n | Cannot find path 'D:\\tasks\\gone.txt' because it does not exist."})
        self.assertTrue(any(row['code'] == 'missing_path' for row in result['diagnostic_findings']))

    def test_encoded_nonzero_exit_survives_json_wrappers(self):
        for wrapper in (lambda x:json.dumps(x),lambda x:{'content':[{'type':'text','text':json.dumps(x)}], 'isError':False}):
            result = classify_output(wrapper({'exit_code': 1, 'stderr': 'Main.java:14: error: missing symbol'}))
            self.assertEqual(result['execution_status'], 'failed')

    def test_nested_mcp_explicit_error_overrides_outer_transport_success(self):
        value={'isError':False,'content':[{'type':'text','text':json.dumps({'isError':True,'content':[{'type':'text','text':'bad input'}]})}]}
        self.assertEqual(classify_output(value)['execution_status'],'failed')
        self.assertEqual(classify_output({'exit_code':0,'stdout':'Yesterday: Error: crashed process'})['execution_status'],'succeeded')

    def test_fixed_revision_uses_revision_path(self):
        calls=[]
        with patch.object(local,'_request',side_effect=lambda url:calls.append(url) or {'id':'test/repo','sha':'a'*40}):
            local._model_inspect('test/repo','a'*40)
        self.assertIn('/revision/'+'a'*40+'?blobs=true',calls[0])

    def test_unreadable_apk_identity_never_reaches_adb_install(self):
        info={'properties':{'ro.build.version.sdk':'34','ro.product.cpu.abi':'arm64-v8a'}}
        with patch.object(local,'_require_device'),patch.object(local,'_device_info',return_value=info), \
             patch.object(local,'_apk_metadata',return_value={'package_name':None}), \
             patch.object(local,'_adb',return_value=(0,'arm64-v8a')) as adb:
            with self.assertRaisesRegex(ValueError,'无法验证 APK 包名'):
                local._install_apks(['bad.apk'],'com.example.test','a'*64)
            self.assertFalse(any(call.args[0].startswith('install') for call in adb.call_args_list))

    def test_abi_and_split_version_rejected_before_install(self):
        info={'properties':{'ro.build.version.sdk':'34','ro.product.cpu.abi':'arm64-v8a'}}
        meta={'package_name':'com.example.test','certificate_sha256':'a'*64,'path':'bad.apk',
              'min_sdk':21,'version_code':1,'native_abis':['x86']}
        with patch.object(local,'_require_device'),patch.object(local,'_device_info',return_value=info), \
             patch.object(local,'_apk_metadata',return_value=meta),patch.object(local,'_adb',return_value=(0,'arm64-v8a')) as adb:
            with self.assertRaisesRegex(ValueError,'ABI'):
                local._install_apks(['bad.apk'],'com.example.test','a'*64)
            self.assertFalse(any(call.args[0].startswith('install') for call in adb.call_args_list))

    def test_legacy_pid_record_cannot_kill_any_process(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'logs').mkdir()
            (root/'logs/design-app-processes.json').write_text(json.dumps({'blender':{'pid':12345}}))
            with patch.object(local,'ROOT',root),patch.object(process_identity,'_kernel',side_effect=AssertionError('should not open process')):
                self.assertFalse(local._stop_design_app('blender')['stopped'])

    @unittest.skipUnless(os.name=='nt','Windows process handles')
    def test_reused_pid_identity_is_refused_without_terminating(self):
        proc=subprocess.Popen(['powershell.exe','-NoProfile','-Command','Start-Sleep -Seconds 20'],creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            actual=process_identity.process_identity(proc.pid)
            self.assertIsNotNone(actual)
            stale={**actual,'creation_filetime':actual['creation_filetime']-1}
            self.assertFalse(process_identity.terminate_verified(stale))
            self.assertIsNone(proc.poll())
            self.assertTrue(process_identity.terminate_verified(actual))
            proc.wait(timeout=5)
        finally:
            if proc.poll() is None:proc.terminate();proc.wait(timeout=5)

    def test_real_degenerate_triangle_and_unit_mismatch_are_not_printable(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'中文 路径.stl'
            tri=trimesh.creation.box(extents=[10,10,10]).triangles.tolist()+[[[0.,0.,0.]]*3]
            with p.open('wb') as stream:
                stream.write(b'fixture'.ljust(80,b'\0'));stream.write(struct.pack('<I',len(tri)))
                for face in tri:stream.write(struct.pack('<12fH',0.,0.,0.,*(v for vertex in face for v in vertex),0))
            p.with_suffix('.units.json').write_text(json.dumps({'unit':'mm','source_parameters':{'fixture':True}}))
            result=stl_inspect(str(p),'m',[10,10,10])
            self.assertEqual(result['degenerate_faces'],1)
            self.assertFalse(result['printable_mesh_basics_pass'])

    def test_health_without_generation_never_creates_capability_evidence(self):
        with self.assertRaises(RuntimeError):
            validation.capability_probes(lambda endpoint,payload:{'status':'ok'}, {'id':'test','supports_tools':True})

    def test_changed_weight_invalidates_previous_runtime_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'model.gguf';path.write_bytes(b'first')
            exe=Path(temp)/'server.exe';exe.write_bytes(b'runtime')
            row={'status':'runtime_validated','supports_tools':True,
                'validation_evidence':{'weight':validation.identity(path),'runtime':validation.identity(exe),
                'probes':{'chinese':{'passed':True},'tools':{'passed':True}}}}
            self.assertTrue(validation.evidence_is_current(row,path))
            path.write_bytes(b'changed model')
            self.assertFalse(validation.evidence_is_current(row,path))

    def test_new_model_capabilities_probe_actual_responses(self):
        replies=[{'choices':[{'message':{'content':'验证成功'}}]},
                 {'choices':[{'message':{'tool_calls':[{'function':{'name':'validation_echo','arguments':'{"value":"ok54"}'}}]}}]},
                 {'choices':[{'message':{'content':'红色'}}]}]
        with patch('model_validation._red_image',return_value='data:image/png;base64,fixture'):
            checked=validation.capability_probes(lambda endpoint,payload:replies.pop(0),{'id':'test','supports_tools':True,'vision':True})
        self.assertTrue(all(item['passed'] for item in checked.values()))


if __name__=='__main__':unittest.main(verbosity=2)
