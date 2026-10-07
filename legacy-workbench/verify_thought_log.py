"""Check live-file tails, complete exports and bounded desktop display."""
import json
from pathlib import Path
import tempfile
import tracemalloc
import unittest
from unittest.mock import patch

import core
from thought_log import TraceTail, VIEW_CHARS, export_trace


def encoded(row):
    return (json.dumps(row,ensure_ascii=False)+'\n').encode('utf-8')

def generated(text,channel='reasoning'):
    return {'event':'generated_delta','channel':channel,'delta':text,'elapsed_seconds':10}


class ThoughtLogChecks(unittest.TestCase):
    def test_live_append_survives_split_json_and_utf8_character(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'live.jsonl';path.write_bytes(b'')
            reader=TraceTail();reader.select(path,tail=False)
            data=encoded(generated('鹈鹕正在规划动画'))
            with path.open('ab') as writer:
                writer.write(data[:-5]);writer.flush()
                self.assertEqual(reader.read(),'')
                writer.write(data[-5:]);writer.flush()
                self.assertIn('鹈鹕正在规划动画',reader.read())
            reader.close()
            self.assertEqual(reader.partial,b'')
            self.assertIsNone(reader.file)

    def test_complete_export_keeps_beginning_beyond_live_view_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'large.jsonl'
            with path.open('wb') as target:
                target.write(encoded(generated('BEGINNING_MARKER\n')))
                for index in range(2000):target.write(encoded(generated('思考内容 '+str(index)+' '+('a'*50)+'\n')))
                target.write(encoded(generated('END_MARKER')))
            reader=TraceTail();reader.select(path)
            tail=reader.read()
            self.assertIn('END_MARKER',tail)
            self.assertNotIn('BEGINNING_MARKER',tail)
            destination=export_trace(path,Path(directory)/'readable')
            contents=destination.read_text(encoding='utf-8')
            self.assertIn('BEGINNING_MARKER',contents)
            self.assertIn('END_MARKER',contents)
            self.assertGreater(len(contents),VIEW_CHARS)
            reader.close()

    def test_large_corrupt_line_does_not_stall_or_accumulate_full_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'bad.jsonl'
            with path.open('wb') as target:
                for _ in range(80):target.write(b'x'*131072)
                target.write(b'\n'+encoded(generated('RECOVERED')))
            reader=TraceTail();reader.select(path,tail=False)
            tracemalloc.start()
            found=False
            for _ in range(100):
                text=reader.read()
                found=found or 'RECOVERED' in text
                self.assertLessEqual(len(reader.partial),524288)
            _,peak=tracemalloc.get_traced_memory();tracemalloc.stop()
            self.assertTrue(found)
            self.assertLess(peak,2*1024*1024)
            reader.close()

    def test_file_generation_phase_and_end_are_distinguished(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'stages.jsonl'
            path.write_bytes(encoded({'event':'item_started','type':'function_call','name':'apply_patch'})+
                encoded(generated('SVG DATA','tool_arguments')))
            reader=TraceTail();reader.select(path,tail=False)
            self.assertIn('apply_patch',reader.read())
            self.assertEqual(reader.phase,'function_call')
            self.assertEqual(reader.tool_name,'apply_patch')
            with path.open('ab') as target:
                target.write(encoded({'event':'request_finished','transport':'client_disconnected'}))
            self.assertIn('已保留收到',reader.read())
            self.assertTrue(reader.finished)
            reader.close()

    def test_ui_bounds_and_selection_use_only_saved_logs(self):
        from app import App
        import app as app_module
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'conversations').mkdir();(root/'logs/generation').mkdir(parents=True)
            path=root/'logs/generation/20261003T000000.000000Z-0123456789ab.jsonl'
            path.write_bytes(encoded(generated('FIRST_RECENT_THOUGHT')))
            settings={'model':core.MODEL,'context':256000,'compact':223232,'project':str(root),
                      'model_contexts':{core.MODEL:256000},'kv_cache_location':'auto','cpu_offload':False}
            with patch.object(app_module,'ROOT',root),patch.object(app_module,'prepare',return_value=settings):
                window=App(smoke=True);window.withdraw()
                try:
                    window.refresh_thought_log()
                    self.assertIn('FIRST_RECENT_THOUGHT',window.thought_box.get('1.0','end'))
                    self.assertEqual(window.thought_reader.path,path)
                    with path.open('ab') as target:
                        for index in range(1300):target.write(encoded(generated('z'*60)))
                    for _ in range(5):window.refresh_thought_log()
                    length=int(window.thought_box._textbox.count('1.0','end-1c','chars')[0])
                    self.assertLessEqual(length,VIEW_CHARS)
                    window.choose_thought_log(window.thought_picker.get())
                    self.assertFalse(window.thought_follow.get())
                    self.assertIn('backend_picker',window.__dict__)
                    self.assertEqual(window.backend_picker.cget('values'),[spec['label'] for spec in core.BACKENDS.values()])
                    self.assertEqual(window.backend_picker.get(),core.BACKENDS['vulkan']['label'])
                    self.assertEqual(settings['context'],256000)
                finally:
                    window.thought_reader.close();window.destroy()

    def test_no_thinking_policy_or_inference_arguments_changed(self):
        self.assertEqual(core.REASONING_BUDGET,-1)
        installed=(core.ROOT/'instructions.md').read_text(encoding='utf-8')
        self.assertEqual(core.INSTRUCTIONS,installed)
        with patch.object(core,'load_settings',return_value={**core.load_settings(),'cpu_offload':False}):
            args=core.model_args(core.MODEL,109568)
        self.assertEqual(args[args.index('--reasoning-budget')+1],'-1')
        self.assertEqual(args[args.index('-n')+1],'-1')
        self.assertEqual(args[args.index('--device')+1],'Vulkan0')


if __name__=='__main__':
    unittest.main(verbosity=2)
