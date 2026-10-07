import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch,Mock
import core
import gateway
from token_speed import TokenSpeed
from moe4all_backend import progress,arguments,normalize_request


class Throughput(unittest.TestCase):
    def test_prefill_does_not_lower_decode_rate_and_stalls_show_zero(self):
        meter=TokenSpeed()
        self.assertEqual(meter.update('a',0,now=0),'')
        self.assertEqual(meter.update('a',0,now=100),'')
        meter.update('a',1,now=101)
        self.assertIn('30.0 token/s',meter.update('a',61,now=103))
        for t in range(104,111):value=meter.update('a',61,now=t)
        self.assertIn('实时 0.0',value)
        self.assertLessEqual(len(meter.samples),64)

    def test_new_request_and_counter_reset_do_not_mix_requests(self):
        meter=TokenSpeed();meter.update((1,1),100,now=0)
        self.assertIn('20.0',meter.update((1,1),120,now=1))
        self.assertIn('测量中',meter.update((1,2),10,now=2))
        self.assertIn('测量中',meter.update((1,2),1,now=3))

    def test_backend_progress_uses_exact_counts_and_marks_done(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'log'
            p.write_text('INFO request start req=4\nINFO request progress req=4 phase=decode gen_tokens=120 decode_tps=30.0\n')
            s=progress(p);self.assertEqual(s['generated_tokens'],120);self.assertTrue(s['is_processing'])
            p.write_text(p.read_text()+'INFO request done req=4 gen_tokens=128 decode_tps=29.8\n')
            self.assertFalse(progress(p)['is_processing'])

class PrefixCache(unittest.TestCase):
    def test_application_updates_preserve_system_and_conversation_prefix(self):
        before={'instructions':'stable system','input':[{'role':'user','content':'original task'},
            {'type':'function_call_output','call_id':'tool1','output':'verified result'}]}
        body=json.loads(json.dumps(before));gateway.append_runtime_state(body,'changing draft count')
        self.assertEqual(body['instructions'],before['instructions'])
        self.assertEqual(body['input'][:-1],before['input'])
        self.assertIn('changing draft count',json.dumps(body['input'][-1]))

    def test_80k_input_uses_gpu_without_adding_output_budget(self):
        s={'model':core.MODEL,'model_contexts':{core.MODEL:276480},'history_mode':'memory',
           'work_context':97280,'backend':'vulkan','kv_cache_location':'auto'}
        self.assertEqual(core.runtime_context_for(s,core.MODEL,80853,core.OUTPUT_RESERVE,current={}),109568)
        self.assertEqual(core.REASONING_BUDGET,-1)
        self.assertEqual(core.runtime_context_for(s,core.MODEL,115000,core.OUTPUT_RESERVE,current={}),276480)

class Backend(unittest.TestCase):
    def test_moe_config_has_no_extra_generation_limit_or_conflicting_kv_modes(self):
        with tempfile.TemporaryDirectory() as folder:
            args=arguments(folder,'infr.exe',{'api_key':'dummy','moe_ssd_cache':False},'model.gguf',None,32768)
            text=(Path(folder)/'cache/moe4all-server.toml').read_text()
            self.assertIn('max_new = 4294967295',text)
            self.assertIn('request_timeout_secs = 0',text)
            self.assertIn('dynamic = true',text);self.assertIn('overflow = false',text)
            self.assertNotIn('--no-think',args)

    def test_meaningful_responses_fields_survive_normalization(self):
        body={'input':'question','prompt_cache_key':'session-key','reasoning_budget_tokens':-1,
              'reasoning':{'effort':'high','summary':'auto'},'max_output_tokens':99}
        clean=normalize_request(body,'/v1/responses')
        self.assertEqual(clean['prompt_cache_key'],'session-key')
        self.assertEqual(clean['max_output_tokens'],99)
        self.assertEqual(clean['reasoning']['effort'],'xhigh')

def verify_widgets():
    import app
    import time
    ui=app.App(smoke=True);ui.withdraw();ui.update()
    checks={}
    try:
        checks['moe_backend_visible']=core.BACKENDS['moe4all']['label'] in ui.backend_picker.cget('values')
        ui.busy=True;ui.turn_id='test';ui.turn_started_at=time.monotonic()
        slot={'is_processing':True,'id_task':1,'next_token':[{'n_decoded':0}],
              'n_prompt_tokens_processed':12000,'n_prompt_tokens_cache':7000}
        with patch.object(app,'server_ready',return_value=True),patch.object(app,'api',return_value=[slot]):
            ui.refresh_status()
            checks['prefill_progress_visible']='正在处理输入' in ui.status.cget('text') and '12,000' in ui.status.cget('text')
            slot['next_token'][0]['n_decoded']=100
            identity=(core.active_model().get('pid'),1,'test')
            ui.token_speed.update(identity,10,now=time.monotonic()-3)
            ui.turn_visible_output=True
            ui.refresh_status()
            checks['speed_visible_after_body_started']='token/s' in ui.status.cget('text')
        ui.input.insert('1.0','previous')
        with patch.object(ui,'send_prompt') as send:
            ui.handle_event({'local':'resume_after_update','text':'resume task'})
            checks['resume_uses_send_prompt']=send.call_count==1 and ui.input.get('1.0','end').strip()=='resume task'
        ui.rpc=Mock()
        with patch.object(app.messagebox,'askyesno',return_value=True),patch.object(ui,'interrupt') as interrupt:
            ui.close_app()
            checks['close_waits_for_native_end']=interrupt.call_count==1 and ui.rpc.close.call_count==0 and ui.winfo_exists()
        ui.rpc=None
    finally:ui.destroy()
    return {'ok':all(checks.values()),'checks':checks}

if __name__=='__main__':unittest.main()
