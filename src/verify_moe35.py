import copy
import json
from pathlib import Path
import tempfile
import tomllib
import unittest
from unittest.mock import patch
import core
import moe4all_backend as moe

class RamProfile(unittest.TestCase):
    def test_ram_profile_preserves_precision_and_unlimited_defaults(self):
        with tempfile.TemporaryDirectory() as folder:
            args=moe.arguments(folder,'infr.exe',{'api_key':'fixture','moe_kv_mode':'ram',
                'moe_vision_enabled':False},'model.gguf','vision.gguf',71680)
            cfg=tomllib.loads((Path(folder)/'cache/moe4all-server.toml').read_text())
            self.assertEqual(cfg['kv']['type_k'],'q8_0')
            self.assertFalse(cfg['kv']['dynamic']);self.assertTrue(cfg['kv']['overflow'])
            self.assertEqual(cfg['kv']['overflow_vram_mb'],512)
            self.assertNotIn('session_cache_dir',cfg['kv'])
            self.assertEqual(cfg['sampling']['max_new'],4294967295)
            self.assertFalse(cfg['sampling']['no_think'])
            self.assertEqual(cfg['sampling']['temp'],1.0)
            self.assertEqual(args[args.index('--ubatch')+1],'16')
            self.assertNotIn('--mmproj',args)
    def test_limits_are_checked_before_loading(self):
        s={'moe_kv_mode':'ram','moe_vision_enabled':False}
        with self.assertRaisesRegex(ValueError,'70K'):moe.validate(s,core.MODEL,73728,{}, {}, 'none')
        with self.assertRaisesRegex(ValueError,'纯文字'):moe.validate({**s,'moe_vision_enabled':True},core.MODEL,71680,{}, {}, 'none')
    def test_child_logging_and_guard(self):
        with patch.dict('os.environ',{'RUST_LOG':'warn','INFR_NO_VRAM_GUARD':'1'}):
            env=core.runtime_environment('moe4all')
            self.assertIn('infr_server=info',env['RUST_LOG'])
            self.assertNotIn('INFR_NO_VRAM_GUARD',env)
    def test_effective_vision_does_not_disable_vulkan_images(self):
        s={'backend':'moe4all','moe_vision_enabled':False,'moe_kv_mode':'ram'}
        self.assertFalse(core.configured_vision(core.MODEL,s))
        self.assertTrue(core.configured_vision(core.MODEL,{**s,'backend':'vulkan'}))
        self.assertEqual(core.kv_cache_location(71680,s),'gpu+ram')
    def test_real_prefill_log_maps_to_progress(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'log'
            p.write_text('INFO request progress req=1 phase="prefill" prefill_tokens=100 prefill_total=400 cached_tokens=20 gen_tokens=0 decode_tps=0.0\n')
            s=moe.progress(p)
            self.assertEqual(s['prefill_tokens'],100);self.assertEqual(s['cached_tokens'],20)
    def test_ram_profile_survives_config_reload(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            candidate={'project':folder,'api_key':'fixture','model':core.MODEL,
                'backend':'moe4all','moe_kv_mode':'ram','moe_vision_enabled':False,
                'history_mode':'memory','work_context':71680,
                'model_contexts':{core.MODEL:71680},'directive_mode':'legacy'}
            with patch.object(core,'ROOT',root),patch.object(Path,'home',return_value=root):
                core.prepare(candidate)
                restored=core.load_settings()
                self.assertEqual(restored['moe_kv_mode'],'ram')
                self.assertFalse(restored['moe_vision_enabled'])
                config=tomllib.loads((root/'codex-home/config.toml').read_text())
                self.assertEqual(config['model_context_window'],71680)
                self.assertLess(config['model_auto_compact_token_limit'],71680)

def widgets():
    import app
    saved=(core.ROOT/'settings.json').read_bytes()
    original=core.load_settings();checks={}
    with patch.object(app,'prepare',return_value=copy.deepcopy(original)):
        ui=app.App(smoke=True);ui.withdraw()
        try:
            ui.backend_picker.set(core.BACKENDS['moe4all']['label'])
            ui.history_picker.set(core.HISTORY_MODES['memory']);ui.work_picker.set('120K')
            ui.preview_context(122880)
            checks['moe_preview_clamps_to_70k']=ui.pending_context==71680 and ui.work_picker.get()=='70K'
            ui.settings={**original,'backend':'moe4all','moe_kv_mode':'ram','moe_vision_enabled':False}
            ui.update_model_labels()
            checks['moe_attachment_disabled']=ui.attach_button.cget('state')=='disabled'
            ui.settings=original;ui.update_model_labels()
            checks['vulkan_attachment_enabled']=ui.attach_button.cget('state')=='normal'
            checks['saved_settings_unchanged']=(core.ROOT/'settings.json').read_bytes()==saved
        finally:ui.destroy()
    return {'ok':all(checks.values()),'checks':checks}

if __name__=='__main__':
    import sys
    if '--widgets' in sys.argv:
        result=widgets();print(json.dumps(result,ensure_ascii=False));sys.exit(0 if result['ok'] else 1)
    unittest.main()
