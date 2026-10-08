"""Targeted regression checks for v53's result classification, drafts and registry."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import local_mcp_servers
from model_catalog import ModelCatalog
from task_artifacts import DraftStream, TaskArtifacts
from tool_results import classify_output
from design_analysis_mcp import compare_design_iterations, compare_fem_runs


class Release53Checks(unittest.TestCase):
    def test_design_analysis_server_script_is_packaged_with_runtime(self):
        root = Path(__file__).parent
        source = (root / 'core.py').read_text(encoding='utf-8')
        spec = (root / 'MyCodex.spec').read_text(encoding='utf-8')
        self.assertIn("analysis_bundle/'mcp-tools'/'design_analysis_mcp.py'", source)
        self.assertIn("datas += [(str(Path(SPECPATH) / 'design_analysis_mcp.py'), 'mcp-tools')]", spec)

    def test_model_activation_and_rollback_queue_respects_verified_state(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            models_dir = root / 'models'
            models_dir.mkdir()
            rows = []
            for model_id, status in (('old-model', 'runtime_validated'),
                                     ('new-model', 'runtime_validated'),
                                     ('unverified-model', 'local_unverified')):
                model_file = models_dir / f'{model_id}.gguf'
                model_file.write_bytes(b'x' * (1024 * 1024))
                rows.append({'id': model_id, 'display_name': model_id, 'filename': model_file.name,
                             'path': str(model_file), 'size_bytes': model_file.stat().st_size,
                             'status': status, 'context_limit': 32768, 'default_context': 16384})
            catalog = ModelCatalog(root, models_dir)
            catalog.write({'schema_version': 1, 'models': rows})
            with patch.object(local_mcp_servers, 'ROOT', root), patch.object(local_mcp_servers, '_catalog', return_value=catalog):
                with self.assertRaisesRegex(ValueError, '尚未通过实际运行时验证'):
                    local_mcp_servers._model_activate('unverified-model')
                local_mcp_servers._model_activate('new-model')
                request_path = root / 'model-activation-request.json'
                request = json.loads(request_path.read_text(encoding='utf-8'))
                self.assertEqual(request['status'], 'queued')
                self.assertEqual(request['model_id'], 'new-model')
                request['status'] = 'applied'
                request_path.write_text(json.dumps(request), encoding='utf-8')
                history = [{'model_id': 'old-model'}, {'model_id': 'new-model'}]
                (root / 'model-activation-history.json').write_text(json.dumps(history), encoding='utf-8')
                rollback = local_mcp_servers._dispatch('model-manager', 'model_rollback', {})
                restored = json.loads(request_path.read_text(encoding='utf-8'))
                self.assertEqual(rollback['status'], 'queued')
                self.assertEqual(restored['status'], 'queued')
                self.assertEqual(restored['model_id'], 'old-model')

    def test_exit_zero_with_old_target_error_is_not_command_failure(self):
        result=classify_output({'exit_code':0,'stdout':'Unknown authority com.miui.cloudservice; app crashed yesterday'})
        self.assertEqual(result['execution_status'],'succeeded')
        self.assertEqual(result['target_validation'],'not_checked')
        self.assertTrue(result['diagnostic_findings'])
        self.assertEqual(result['diagnostic_findings'][0]['attribution'],'unverified')

    def test_structured_mcp_error_inside_json_text_is_tool_failure(self):
        result=classify_output('{"content":[{"type":"text","text":"bad"}],"isError":true}')
        self.assertEqual(result['execution_status'],'failed')
        self.assertTrue(any(row['code']=='mcp_reported_error' for row in result['diagnostic_findings']))

    def test_compile_error_keeps_command_and_target_failure_distinct(self):
        result=classify_output({'exit_code':1,'stderr':'Main.java:14: error: cannot find symbol\nBUILD FAILED'})
        self.assertEqual(result['execution_status'],'failed')
        self.assertEqual(result['target_validation'],'reported_failure')
        self.assertTrue(any(row.get('line')==14 for row in result['diagnostic_findings']))

    def test_nonterminating_powershell_text_does_not_override_exit_zero(self):
        result=classify_output({'exit_code':0,'stderr':'Get-Item : Cannot find path\nFullyQualifiedErrorId : PathNotFound'})
        self.assertEqual(result['execution_status'],'succeeded')
        self.assertTrue(result['diagnostic_findings'])

    def test_draft_repeated_read_dedup_and_force_reread(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); project=root/'project'; project.mkdir()
            task,locks=TaskArtifacts(root/'history').begin('12345678-1234-1234-1234-123456789abc',project,'生成SVG插画')
            stream=DraftStream(task['draft_directory'],'abcdef123456')
            stream.feed('assistant','```python\nprint(1)\n```\n');stream.close();locks.close()
            draft=TaskArtifacts(root/'history').list('12345678-1234-1234-1234-123456789abc')['drafts'][0]['id']
            first=TaskArtifacts(root/'history').read('12345678-1234-1234-1234-123456789abc',draft)
            second=TaskArtifacts(root/'history').read('12345678-1234-1234-1234-123456789abc',draft)
            forced=TaskArtifacts(root/'history').read('12345678-1234-1234-1234-123456789abc',draft,force=True)
            self.assertEqual(first['text'],'print(1)\n')
            self.assertTrue(second['already_read_unchanged'])
            self.assertEqual(second['text'],'')
            self.assertFalse(forced['already_read_unchanged'])
            self.assertEqual(forced['text'],first['text'])

    def test_model_catalog_is_shared_versioned_and_reloads_external_edits(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); models=root/'models'; models.mkdir()
            catalog=ModelCatalog(root,models)
            self.assertIn('Huihui-Qwen3.8-27B-abliterated-GSQ-RCO-IQ3_S',catalog)
            data=json.loads(catalog.path.read_text(encoding='utf-8'))
            data['models'].append({'id':'future-local-test','display_name':'Future local test','provider':'local',
                'filename':'future.gguf','path':None,'size_bytes':0,'context_limit':16384,
                'default_context':8192,'vision':False,'projector_filename':None,'status':'local_unverified'})
            catalog.write(data)
            self.assertEqual(catalog['future-local-test']['context_limit'],16384)
            self.assertEqual(catalog['future-local-test']['label'],'Future local test')

    def test_design_process_state_does_not_overwrite_app_configuration(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            config=root/'design-apps.json'
            original={'blender':{'executable':'G:/tools/blender.exe','port':9876}}
            config.write_text(json.dumps(original),encoding='utf-8')
            with patch.object(local_mcp_servers,'ROOT',root):
                local_mcp_servers._write_design_processes({'blender':{'pid':1234}})
            self.assertEqual(json.loads(config.read_text(encoding='utf-8')),original)
            self.assertEqual(json.loads((root/'logs'/'design-app-processes.json').read_text(encoding='utf-8')),
                             {'blender':{'pid':1234}})

    def _write_fem_manifest(self, root, name, geometry, mesh_size, nodes, disp, stress):
        result = root / (name + '.FCStd')
        result.write_bytes(b'actual saved FEM result container')
        manifest = {'solver': {'name': 'CalculiX', 'status': 'completed', 'result_file': str(result)},
            'geometry': geometry, 'material': {'name': 'Steel', 'youngs_modulus_GPa': 210, 'poisson_ratio': 0.3},
            'units': {'length': 'mm', 'force': 'N', 'stress': 'MPa'},
            'boundary_conditions': {'fixed_face': 'x=0'}, 'load': {'face': 'x=100', 'force_N': 100, 'direction': '-Z'},
            'mesh': {'max_element_size_mm': mesh_size, 'node_count': nodes},
            'max_displacement': {'value': disp, 'unit': 'mm'},
            'max_von_mises': {'value': stress, 'unit': 'MPa'}}
        path = root / (name + '.json')
        path.write_text(json.dumps(manifest), encoding='utf-8')
        return path

    def test_fem_mesh_comparison_requires_distinct_real_mesh_results(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            coarse=self._write_fem_manifest(root,'coarse',{'length_mm':100,'width_mm':10,'height_mm':10},5,198,.114,30.6)
            fine=self._write_fem_manifest(root,'fine',{'length_mm':100,'width_mm':10,'height_mm':10},3,735,.156,44.9)
            result=compare_fem_runs(str(coarse),str(fine))
            self.assertTrue(result['comparable'])
            self.assertEqual(result['comparison_kind'],'mesh_refinement')
            self.assertTrue(Path(result['report_path']).is_file())
            same=self._write_fem_manifest(root,'same',{'length_mm':100,'width_mm':10,'height_mm':10},3,735,.156,44.9)
            with self.assertRaisesRegex(ValueError,'节点数没有变化'):
                compare_fem_runs(str(fine),str(same))

    def test_fem_design_iteration_records_geometry_change_separately(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            before=self._write_fem_manifest(root,'before',{'length_mm':100,'width_mm':10,'height_mm':10},3,735,.156,44.9)
            after=self._write_fem_manifest(root,'after',{'length_mm':100,'width_mm':10,'height_mm':12},3,820,.093,32.4)
            result=compare_design_iterations(str(before),str(after))
            self.assertEqual(result['comparison_kind'],'design_iteration')
            self.assertEqual(result['geometry_before']['height_mm'],10)
            self.assertGreater(result['displacement_relative_change'],0.3)
            self.assertTrue(Path(result['report_path']).is_file())


if __name__=='__main__':
    unittest.main(verbosity=2)
