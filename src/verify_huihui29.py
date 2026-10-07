"""Verify Huihui vision input and preserve the original Jack launch policy."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import core
import gateway
import app


class HuihuiModel(unittest.TestCase):
    def test_model_requires_its_projector_and_launches_both_on_gpu(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);model=root/(core.HUIHUI_IQ3S_MODEL+'.gguf');model.write_bytes(b'fixture')
            projector=root/'mmproj.gguf';projector.write_bytes(b'projector fixture')
            settings={**core.load_settings(),'model':core.HUIHUI_IQ3S_MODEL,'emotion_mode':'off',
                'emotion_secondary_mode':'off','speculative_type':'draft-mtp','cpu_offload':False,'kv_cache_location':'gpu'}
            with patch.object(core,'MODEL_DIRECTORY',root),patch.object(core,'VISION_FILE',projector),patch.object(core,'load_settings',return_value=settings):
                self.assertEqual(core.model_required_files(core.HUIHUI_IQ3S_MODEL),[model,projector])
                self.assertGreater(core.gpu_memory_required_mib(core.HUIHUI_IQ3S_MODEL,76800),1024)
                args=core.model_args(core.HUIHUI_IQ3S_MODEL,76800)
                for flag in ('--chat-template-file','--control-vector-scaled'):
                    self.assertNotIn(flag,args)
                self.assertEqual(args[args.index('--mmproj')+1],str(projector))
                self.assertIn('--mmproj-offload',args)
                self.assertIn('--image-max-tokens',args)
                self.assertEqual(args[args.index('-ngl')+1],'all')
                self.assertIn('--kv-offload',args)
                self.assertEqual(args[args.index('--reasoning-budget')+1],'-1')
                self.assertEqual(args[args.index('--spec-type')+1],'none')

    def test_original_jack_arguments_are_unchanged(self):
        from importlib.util import spec_from_file_location,module_from_spec
        status=json.loads((core.ROOT/'huihui29-stop-status.json').read_text())
        path=Path(status['backup'])/'core.py'
        spec=spec_from_file_location('core_before29',path);old=module_from_spec(spec);spec.loader.exec_module(old)
        settings={**core.load_settings(),'emotion_mode':'off','emotion_secondary_mode':'off'}
        with patch.object(old,'load_settings',return_value=settings),patch.object(core,'load_settings',return_value=settings):
            previous=old.model_args(core.MODEL,109568)
            # v32 retains four bounded recurrent checkpoints to restore a
            # prefix after late application-state edits; all other flags stay.
            previous[previous.index('--ctx-checkpoints')+1]='4'
            self.assertEqual(previous,core.model_args(core.MODEL,109568))

    def test_catalog_and_private_native_profile_include_vision(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);settings={**core.load_settings(),'model':core.HUIHUI_IQ3S_MODEL,
                'history_mode':'memory','work_context':core.WORK_CONTEXT,
                'model_contexts':{core.HUIHUI_IQ3S_MODEL:core.WORK_CONTEXT}}
            with patch.object(core,'ROOT',root),patch.object(core.Path,'home',return_value=root/'no-home'):
                core.prepare(settings)
            models=json.loads((root/'model-catalog.json').read_text())['models']
            text=next(model for model in models if model['slug']==core.HUIHUI_IQ3S_MODEL)
            self.assertEqual(text['input_modalities'],['text','image'])
            self.assertEqual((text['context_window'],text['auto_compact_token_limit']),(core.WORK_CONTEXT,core.WORK_COMPACT))
            self.assertTrue((root/'codex-home/huihui-iq3s-local.config.toml').exists())
            self.assertIn('image',next(model for model in models if model['slug']==core.MODEL)['input_modalities'])

    def test_picture_inputs_are_detected_but_tool_schema_is_not_picture_input(self):
        self.assertTrue(gateway.contains_input_images({'input':[{'role':'user','content':[{'type':'input_image','image_url':'x'}]}]}))
        self.assertTrue(gateway.contains_input_images({'messages':[{'role':'user','content':[{'type':'image_url','image_url':{'url':'x'}}]}]}))
        self.assertFalse(gateway.contains_input_images({'input':'Hello','tools':[{'type':'function','parameters':{'type':'image'}}]}))

    def test_actual_widgets_show_complete_vision_download_and_enable_images(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'probe.txt').write_text('UI fixture')
            settings={**core.load_settings(),'project':str(root),'model':core.HUIHUI_IQ3S_MODEL,
                'emotion_mode':'off','emotion_secondary_mode':'off'}
            with patch.object(app,'ROOT',root),patch.object(app,'prepare',return_value=settings),patch.object(app,'server_ready',return_value=False):
                ui=app.App(smoke=True)
                try:
                    ui.withdraw();ui.update();ui.refresh_status()
                    self.assertIn(core.MODELS[core.HUIHUI_IQ3S_MODEL]['label'],ui.model_picker.cget('values'))
                    self.assertEqual(ui.pending_model(),core.HUIHUI_IQ3S_MODEL)
                    self.assertEqual(ui.attach_button.cget('state'),'normal')
                    self.assertEqual(ui.attach_button.cget('text'),'添加图片')
                    self.assertIn('模型与视觉组件：100.0%',ui.model_info.cget('text'))
                    self.assertEqual(ui.emotion_picker.cget('state'),'disabled')
                    self.assertEqual(ui.emotion_secondary_picker.cget('state'),'disabled')
                finally:
                    for timer in ui.tk.call('after','info'):ui.tk.call('after','cancel',timer)
                    ui.artifact_locks.close();ui.destroy()

    def test_old_text_only_server_is_not_reused_after_vision_update(self):
        from emotion_vectors import emotion_state
        settings={**core.load_settings(),'model':core.HUIHUI_IQ3S_MODEL,
            'model_contexts':{core.HUIHUI_IQ3S_MODEL:97280},'emotion_mode':'off',
            'emotion_secondary_mode':'off','speculative_type':'none'}
        live={'model':core.HUIHUI_IQ3S_MODEL,'context':97280,'context_limit':97280,
            'backend':core.selected_backend(settings),'performance_mode':settings.get('performance_mode','standard'),
            'speculative_type':'none','reasoning_budget':-1,'kv_cache_location':core.kv_cache_location(97280,settings),
            'chat_template_policy':'embedded','chat_template_sha256':None,
            'emotion_signature':emotion_state(core.ROOT,core.model_file(core.HUIHUI_IQ3S_MODEL),settings)['signature']}
        self.assertFalse(core.runtime_matches_settings(live,settings))
        self.assertTrue(core.runtime_matches_settings({**live,'vision_enabled':True},settings))


if __name__=='__main__':unittest.main(verbosity=2)
