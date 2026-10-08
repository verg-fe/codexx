"""Check selectable large working windows without loading long model inputs."""
import copy
import json
from pathlib import Path
import tempfile
import tomllib
import unittest
from unittest.mock import patch
import core


class WorkOptions(unittest.TestCase):
    def test_requested_options_reach_native_context_and_compaction(self):
        settings={'model':core.MODEL,'history_mode':'memory','model_contexts':{core.MODEL:276480}}
        self.assertTrue(set(range(100,231,10)).issubset(core.WORK_CONTEXT_OPTIONS))
        for k in range(100,231,10):
            with self.subTest(k=k):
                candidate={**settings,'work_context':k*1024}
                self.assertEqual(core.engine_limits(candidate),(k*1024,(k-16)*1024))
                self.assertEqual(core.engine_config(candidate)['model_context_window'],k*1024)

    def test_default_and_model_cap_remain_valid(self):
        settings={'model':core.MODEL,'history_mode':'memory','model_contexts':{core.MODEL:276480}}
        self.assertEqual(core.engine_limits(settings),(97280,83968))
        self.assertEqual(core.engine_limits({**settings,'work_context':999999})[0],235520)
        self.assertEqual(core.engine_limits({**settings,'model_contexts':{core.MODEL:40960},'work_context':235520})[0],40960)

    def test_saved_large_work_window_is_not_reduced_to_95k(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            settings={'api_key':'fixture-only','project':str(root),'model':core.HUIHUI_IQ3S_MODEL,
                'backend':'vulkan','history_mode':'memory','work_context':235520,
                'model_contexts':{core.HUIHUI_IQ3S_MODEL:235520},'directive_mode':'legacy'}
            with patch.object(core,'ROOT',root),patch.object(Path,'home',return_value=root/'private-home'):
                core.prepare(settings)
                self.assertEqual(core.load_settings()['work_context'],235520)
                config=tomllib.loads((root/'codex-home/config.toml').read_text(encoding='utf-8'))
                self.assertEqual((config['model_context_window'],config['model_auto_compact_token_limit']),(235520,219136))


def verify_widgets():
    import app
    saved=(core.ROOT/'settings.json').read_bytes()
    checks={};ui=None
    with patch.object(Path,'home',return_value=core.ROOT/'private-test-home'):
        try:
            ui=app.App(smoke=True);ui.withdraw();ui.update()
            original=copy.deepcopy(ui.settings)
            expected=[f'{k}K' for k in range(100,231,10)]
            checks['all_requested_options_visible']=all(x in ui.work_picker.cget('values') for x in expected)
            ui.history_picker.set(core.HISTORY_MODES['memory'])
            ui.model_picker.set(core.MODELS[core.HUIHUI_IQ3S_MODEL]['label']);ui.preview_model(ui.model_picker.get())
            ui.work_picker.set('230K');ui.preview_context(ui.context_slider.get())
            checks['larger_selection_expands_pending_model_ceiling']=ui.pending_context>=235520
            checks['230k_and_214k_compact_preview']='235,520' in ui.context_value.cget('text') and '219,136' in ui.context_value.cget('text')
            checks['preview_does_not_apply_settings']=ui.settings==original and (core.ROOT/'settings.json').read_bytes()==saved
            checks['slider_stays_memory_mode_disabled']=ui.context_slider.cget('state')=='disabled'
            ui.work_picker.set('100K');ui.preview_context(ui.context_slider.get())
            checks['100k_and_84k_compact_preview']='102,400' in ui.context_value.cget('text') and '86,016' in ui.context_value.cget('text')
            ui.destroy();ui=None
            candidate={**original,'work_context':235520,'model_contexts':{**original['model_contexts'],original['model']:235520}}
            core.prepare(candidate)
            config=tomllib.loads((core.ROOT/'codex-home/config.toml').read_text(encoding='utf-8'))
            checks['frozen_prepare_retains_230k']=core.load_settings()['work_context']==235520
            checks['frozen_native_config_230k_214k']=(config['model_context_window'],config['model_auto_compact_token_limit'])==(235520,219136)
        finally:
            if ui:ui.destroy()
            core.prepare(json.loads(saved))
    return {'ok':all(checks.values()),'checks':checks,'no_model_load_or_long_prompt':True,'units':'1K = 1024 tokens'}


if __name__=='__main__':unittest.main()
