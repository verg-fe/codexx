"""Regress token accounting, unbounded thinking and dynamic cache routing."""
import copy
import json
import unittest
from unittest.mock import patch

import core
import gateway


SETTINGS={'model':core.MODEL,'model_contexts':{core.MODEL:256000},
          'kv_cache_location':'auto','cpu_offload':False,'api_key':'test-only'}


class DynamicContextChecks(unittest.TestCase):
    def test_ceiling_does_not_force_short_chat_into_ram(self):
        self.assertEqual(core.runtime_context_for(SETTINGS,core.MODEL,current={}),109568)
        self.assertEqual(core.runtime_context_for(SETTINGS,core.MODEL,15444,current={}),109568)
        self.assertEqual(core.runtime_context_for(SETTINGS,core.MODEL,100000,current={}),256000)

    def test_generation_reserve_is_used_at_boundary(self):
        edge=core.GPU_CONTEXT_LIMIT-core.OUTPUT_RESERVE
        self.assertEqual(core.runtime_context_for(SETTINGS,core.MODEL,edge,current={}),109568)
        self.assertEqual(core.runtime_context_for(SETTINGS,core.MODEL,edge+1,current={}),256000)
        self.assertEqual(core.runtime_context_for(SETTINGS,core.MODEL,100000,256,current={}),109568)

    def test_manual_choices_and_small_windows_are_preserved(self):
        for choice in ('gpu','ram'):
            settings={**SETTINGS,'kv_cache_location':choice}
            self.assertEqual(core.runtime_context_for(settings,core.MODEL,1,current={}),256000)
        settings={**SETTINGS,'model_contexts':{core.MODEL:20480}}
        self.assertEqual(core.runtime_context_for(settings,core.MODEL,1,current={}),20480)

    def test_large_cache_reused_between_tools_and_released_after_compaction(self):
        current={'model':core.MODEL,'context_limit':256000,'context':256000,'kv_cache_location':'ram'}
        self.assertEqual(core.runtime_context_for(SETTINGS,core.MODEL,current=current),256000)
        self.assertEqual(core.runtime_context_for(SETTINGS,core.MODEL,65000,current=current),256000)
        self.assertEqual(core.runtime_context_for(SETTINGS,core.MODEL,30000,current=current),109568)

    def test_readiness_accepts_gpu_service_under_256k_ceiling(self):
        live={'model':core.MODEL,'context':109568,'context_limit':256000,'reasoning_budget':-1,'kv_cache_location':'gpu'}
        self.assertTrue(core.runtime_matches_settings(live,SETTINGS))
        self.assertFalse(core.runtime_matches_settings({**live,'reasoning_budget':1024},SETTINGS))

    def test_all_efforts_have_no_injected_limit(self):
        for effort in ('minimal','low','medium','high','xhigh'):
            body=gateway.normalize({'input':[],'reasoning':{'effort':effort},'thinking_budget_tokens':100})
            self.assertEqual(body['reasoning_budget_tokens'],-1)
            self.assertNotIn('thinking_budget_tokens',body)
            self.assertNotIn('max_output_tokens',body)
        body=gateway.normalize({'input':[],'max_output_tokens':50000})
        self.assertEqual(body['max_output_tokens'],50000)

    def test_cli_disables_reasoning_and_total_generation_caps(self):
        with patch.object(core,'load_settings',return_value=SETTINGS):
            args=core.model_args(core.MODEL,109568)
        self.assertEqual(args[args.index('--reasoning-budget')+1],'-1')
        self.assertEqual(args[args.index('-n')+1],'-1')
        self.assertIn('--kv-offload',args)
        self.assertEqual(args[args.index('-ngl')+1],'all')

    def test_counting_preserves_reasoning_tool_calls_results_and_schemas(self):
        body={'instructions':'system','input':[
            {'role':'user','content':'write a file'},
            {'type':'reasoning','summary':[],'content':[{'type':'reasoning_text','text':'previous reasoning'}]},
            {'type':'message','role':'assistant','content':[{'type':'output_text','text':'working'}]},
            {'type':'custom_tool_call','name':'apply_patch','call_id':'a','input':'*** Begin Patch'},
            {'type':'custom_tool_call_output','call_id':'a','output':'done'},
            {'role':'user','content':[{'type':'input_text','text':'continue'}]}],
            'tools':[{'type':'custom','name':'apply_patch','description':'edit','format':{}}]}
        normalized=gateway.normalize(copy.deepcopy(body))
        saved=copy.deepcopy(normalized)
        chat=gateway.responses_chat(normalized)
        self.assertEqual(normalized,saved)
        self.assertEqual([m['role'] for m in chat['messages']],['system','user','assistant','tool','user'])
        assistant=chat['messages'][2]
        self.assertEqual(assistant['reasoning_content'],'previous reasoning')
        self.assertEqual(assistant['content'][0]['text'],'working')
        self.assertEqual(json.loads(assistant['tool_calls'][0]['function']['arguments'])['input'],'*** Begin Patch')
        self.assertEqual(chat['tools'][0]['function']['parameters']['required'],['input'])

    def test_actual_tokenizer_includes_special_tokens_and_image_headroom(self):
        calls=[]
        def fake_api(path,body,timeout):
            calls.append((path,body))
            return {'prompt':'rendered template'} if path=='/apply-template' else {'tokens':[1,2,3]}
        body={'input':[{'role':'user','content':[{'type':'input_image','image_url':'data:image/png;base64,PRIVATE'}]}]}
        with patch.object(gateway,'api',side_effect=fake_api):
            count=gateway.count_prompt_tokens(body,'/v1/responses')
        self.assertEqual(count,2051)
        self.assertNotIn('PRIVATE',json.dumps(calls))
        self.assertTrue(calls[1][1]['add_special'])

    def test_uncountable_request_uses_full_window(self):
        live={'context':256000,'kv_cache_location':'ram'}
        with patch.object(gateway,'ROOT') as root, patch.object(gateway,'start_model') as start, \
                patch.object(gateway,'active_model',return_value=live), \
                patch.object(gateway,'count_prompt_tokens',side_effect=ValueError('unknown')):
            gateway.route_inference({},'/v1/responses',SETTINGS,core.MODEL)
        self.assertTrue(start.call_args.kwargs['full_context'])


if __name__=='__main__':
    unittest.main(verbosity=2)
