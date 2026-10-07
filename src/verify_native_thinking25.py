"""Check protocol preservation without loading another model or changing user settings."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import core
from gguf_info import read_metadata
from model_templates import INJECTION, native_thinking_template, ensure_native_template

sys.path.insert(0, str(core.ROOT / 'verification-deps/native25'))
from jinja2 import Environment, StrictUndefined


class TemplateChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = core.model_file(core.MODEL)
        cls.before = cls.model.stat()
        cls.original = read_metadata(cls.model)['tokenizer.chat_template']
        cls.override, cls.directive = native_thinking_template(cls.original)
        cls.settings = core.load_settings()

    @classmethod
    def tearDownClass(cls):
        after = cls.model.stat()
        assert (after.st_size, after.st_mtime_ns) == (cls.before.st_size, cls.before.st_mtime_ns)

    def render(self, template, messages, tools=None, effort='medium', thinking=True):
        env = Environment()
        env.globals['raise_exception'] = lambda message: (_ for _ in ()).throw(ValueError(message))
        return env.from_string(template).render(messages=messages, tools=tools or [],
            add_generation_prompt=True, enable_thinking=thinking, preserve_thinking=True,
            reasoning_effort=effort, add_vision_id=False)

    def compare(self, messages, tools=None, effort='medium', thinking=True):
        old = self.render(self.original, messages, tools, effort, thinking)
        new = self.render(self.override, messages, tools, effort, thinking)
        # The supplied messages, tool JSON, media markers and assistant think prefix must match.
        old_prefix, old_tail = old.split('<|im_end|>', 1)
        new_prefix, new_tail = new.split('<|im_end|>', 1)
        expected = old_prefix.replace(self.directive + '\n\n', '', 1).replace(self.directive, '', 1)
        self.assertEqual(new_prefix, expected)
        self.assertEqual(new_tail, old_tail)
        self.assertNotIn('<Prime_Directive>', new_prefix)
        return new

    def test_text_effort_and_native_thinking_prefix_preserved(self):
        messages=[{'role':'system','content':'HELPER_SYSTEM'}, {'role':'user','content':'你好'}]
        for effort in ('low','medium','xhigh'):
            with self.subTest(effort=effort):
                rendered=self.compare(messages,effort=effort)
                self.assertTrue(rendered.endswith('<think>\n'))
        off=self.compare(messages,thinking=False)
        self.assertTrue(off.endswith('<think>\n\n</think>\n\n'))

    def test_tool_call_roundtrip_and_prior_thinking_retained(self):
        tools=[{'type':'function','function':{'name':'ping','description':'probe','parameters':
            {'type':'object','properties':{'message':{'type':'string'}},'required':['message']}}}]
        messages=[{'role':'system','content':'HELPER_SYSTEM'}, {'role':'user','content':'Use ping.'},
            {'role':'assistant','content':'','reasoning_content':'<workspace_state>OLD_STATE</workspace_state>',
             'tool_calls':[{'function':{'name':'ping','arguments':{'message':'ok'}}}]},
            {'role':'tool','content':'ACTUAL_TOOL_RESULT'}]
        result=self.compare(messages,tools)
        self.assertIn('ACTUAL_TOOL_RESULT',result)
        self.assertIn('OLD_STATE',result)
        self.assertIn('<function=ping>',result)

    def test_vision_markers_preserved(self):
        messages=[{'role':'system','content':'HELPER_SYSTEM'}, {'role':'user','content':[
            {'type':'text','text':'Describe this picture'}, {'type':'image','image':'fixture'}]}]
        result=self.compare(messages)
        self.assertIn('<|vision_start|><|image_pad|><|vision_end|>',result)

    def test_server_args_and_policy_match(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(core,'ROOT',Path(folder)):
            enabled={**self.settings,'jack_xml_enabled':True,'directive_mode':'legacy','emotion_mode':'off'}
            disabled={**self.settings,'jack_xml_enabled':False,'directive_mode':'native','emotion_mode':'off'}
            with patch.object(core,'load_settings',return_value=enabled):
                old=core.model_args(core.MODEL,core.GPU_CONTEXT_LIMIT)
                self.assertNotIn('--chat-template-file',old)
            with patch.object(core,'load_settings',return_value=disabled):
                new=core.model_args(core.MODEL,core.GPU_CONTEXT_LIMIT)
                index=new.index('--chat-template-file')
                self.assertEqual(new[:index]+new[index+2:],old)
                info=core.chat_template_state(core.MODEL,disabled)
                self.assertEqual(Path(info['file']).read_text(encoding='utf-8'),self.override)
                live={**core.active_model(),'model':core.MODEL,'context':core.GPU_CONTEXT_LIMIT,
                    'context_limit':core.context_for(disabled,core.MODEL),'backend':disabled['backend'],
                    'performance_mode':disabled['performance_mode'],'speculative_type':'none','reasoning_budget':-1,'kv_cache_location':'gpu'}
                self.assertFalse(core.runtime_matches_settings(live,disabled))
                live.update(chat_template_policy=info['policy'],chat_template_sha256=info['sha256'])
                self.assertTrue(core.runtime_matches_settings(live,disabled))
                self.assertFalse(core.runtime_matches_settings(live,enabled))
                other=core.model_args(core.HUIHUI_MODEL,20480)
                self.assertNotIn('--chat-template-file',other)

    def test_unknown_template_and_modified_override_fail_closed(self):
        with self.assertRaises(ValueError):native_thinking_template('UNKNOWN_TEMPLATE')
        with tempfile.TemporaryDirectory() as folder:
            info=ensure_native_template(folder,self.model)
            Path(info['file']).write_text('modified',encoding='utf-8')
            with self.assertRaises(ValueError):ensure_native_template(folder,self.model)


if __name__=='__main__':
    unittest.main()
