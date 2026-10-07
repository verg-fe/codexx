import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import core
from gateway import adapt_event,normalize,tool_response_routes,retain_execution_state
from history_memory import HistoryMemory,memory_instructions
from execution_memory import result_status

TID='11111111-1111-4111-8111-111111111111'

class RoutingChecks(unittest.TestCase):
    def test_namespace_roundtrip_and_resend(self):
        body={'tools':[{'type':'namespace','name':'mcp__local_history','tools':[{
            'type':'function','name':'history_read','parameters':{'type':'object'}}]}],
            'input':[]}
        routes,names=tool_response_routes(body['tools']);normalized=normalize(copy.deepcopy(body))
        flat=normalized['tools'][0]['name'];self.assertEqual(flat,'mcp__local_history__history_read')
        item={'type':'function_call','id':'i','call_id':'c','name':flat,'arguments':'{}'}
        data=adapt_event({'type':'response.output_item.done','item':item},names,set(),routes)[0]
        self.assertEqual(data['item']['name'],'history_read');self.assertEqual(data['item']['namespace'],'mcp__local_history')
        resent=normalize({'input':[copy.deepcopy(data['item'])]})['input'][0]
        self.assertEqual(resent['name'],flat);self.assertNotIn('namespace',resent)
    def test_terminal_response_and_custom_namespace_are_restored(self):
        tools=[{'type':'namespace','name':'edits','tools':[{'type':'custom','name':'apply_patch'}]}]
        routes,names=tool_response_routes(tools);ids=set()
        item={'type':'function_call','id':'i','name':'edits__apply_patch','arguments':json.dumps({'input':'PATCH'})}
        adapted=adapt_event({'type':'response.output_item.added','item':copy.deepcopy(item)},names,ids,routes)[0]['item']
        self.assertEqual((adapted['type'],adapted['name'],adapted['namespace']),('custom_tool_call','apply_patch','edits'))
        output=adapt_event({'type':'response.completed','response':{'output':[copy.deepcopy(item)]}},names,ids,routes)[0]
        self.assertEqual(output['response']['output'][0]['input'],'PATCH')
        events=adapt_event({'type':'response.function_call_arguments.done','item_id':'i','arguments':item['arguments']},names,ids,routes)
        self.assertEqual(events[0]['delta'],'PATCH')
    def test_unknown_tool_is_not_guessed_and_plain_names_are_unchanged(self):
        routes,names=tool_response_routes([{'type':'function','name':'literal__name'}])
        item={'type':'function_call','name':'mcp__unknown__dangerous','arguments':'{}'}
        before=copy.deepcopy(item)
        self.assertEqual(adapt_event({'type':'response.output_item.done','item':item},names,set(),routes)[0]['item'],before)

class ExecutionChecks(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.memory=HistoryMemory(self.root)
        self.path=self.root/'codex-home/sessions'/('rollout-'+TID+'.jsonl');self.path.parent.mkdir(parents=True)
        self.path.touch();self.append('event_msg',{'type':'task_started','turn_id':'turn-one'})
    def tearDown(self):self.temp.cleanup()
    def append(self,kind,payload):
        with self.path.open('a',encoding='utf-8') as f:f.write(json.dumps({'timestamp':'2026-10-03T00:00:00Z','type':kind,'payload':payload},ensure_ascii=False)+'\n')
    def action(self,call,cmd,code):
        self.append('response_item',{'type':'function_call','name':'exec_command','call_id':call,'arguments':json.dumps({'cmd':cmd})})
        self.append('response_item',{'type':'function_call_output','call_id':call,'output':f'Process exited with code {code}\nOutput:\n'+('SyntaxError: BROKEN_QUOTING' if code else 'OK')})
    def test_failure_survives_compaction_and_exact_record_can_be_read(self):
        self.action('a','python -c broken quoting',1)
        before=self.path.read_bytes();state=self.memory.execution_snapshot(TID)
        self.assertEqual(len(state['failures']),1);self.assertEqual(self.path.read_bytes(),before)
        self.append('compacted',{'message':'SUMMARY OMITTING THE FAILURE'})
        self.action('b','read file',0)
        body=normalize({'instructions':memory_instructions(TID),'input':[{'role':'user','content':'Continue'}]})
        self.assertEqual(retain_execution_state(body,self.memory),1)
        self.assertNotIn('BROKEN_QUOTING',body['instructions'])
        self.assertIn('BROKEN_QUOTING',json.dumps(body['input']))
        failed=self.memory.checkpoint(TID)['execution']['failures'][0]
        self.assertIn('BROKEN_QUOTING',self.memory.read(TID,failed['record_id'])['text'])
        self.assertIn('broken quoting',self.memory.read(TID,failed['call_record_id'])['text'])
    def test_same_action_success_supersedes_but_other_success_does_not(self):
        self.action('a','retry',1);self.action('b','unrelated',0)
        self.assertEqual(len(self.memory.execution_snapshot(TID)['failures']),1)
        self.action('c','retry',0);self.assertFalse(self.memory.execution_snapshot(TID)['failures'])
        with self.memory.connect() as db:self.assertEqual(db.execute("SELECT count(*) FROM execution_results WHERE status='failed'").fetchone()[0],1)
    def test_partial_record_pending_call_and_restart_are_incremental(self):
        self.append('response_item',{'type':'function_call','name':'exec_command','call_id':'a','arguments':'{"cmd":"retry"}'})
        self.assertFalse(self.memory.execution_snapshot(TID)['failures'])
        line=json.dumps({'type':'response_item','payload':{'type':'function_call_output','call_id':'a','output':'Process exited with code 1\nFAIL中文'}}).encode()+b'\n'
        with self.path.open('ab') as f:f.write(line[:-4])
        self.assertFalse(self.memory.execution_snapshot(TID)['failures'])
        with self.path.open('ab') as f:f.write(line[-4:])
        restarted=HistoryMemory(self.root)
        self.assertEqual(len(restarted.execution_snapshot(TID)['failures']),1)
        self.assertEqual(len(restarted.execution_snapshot(TID)['failures']),1)
    def test_only_current_turn_is_in_prompt_but_old_failures_stay_on_disk(self):
        self.action('a','old',1);self.memory.execution_snapshot(TID)
        self.append('event_msg',{'type':'task_started','turn_id':'turn-two'})
        self.assertFalse(self.memory.execution_snapshot(TID)['failures'])
        with self.memory.connect() as db:self.assertEqual(db.execute('SELECT count(*) FROM execution_results').fetchone()[0],1)
    def test_mcp_and_patch_errors_and_success_text_containing_exception(self):
        self.assertEqual(result_status('unsupported call: mcp__local_history__history_read')[0],'failed')
        self.assertEqual(result_status({'isError':True,'content':[]})[0],'failed')
        self.assertEqual(result_status('apply_patch verification failed: no match')[0],'failed')
        self.assertEqual(result_status('Process exited with code 0\nSyntaxError: printed example')[0],'succeeded')
    def test_snapshot_is_bounded_and_does_not_parse_long_reasoning(self):
        self.append('response_item',{'type':'reasoning','content':[{'text':'x'*(2*1024*1024)}]})
        for i in range(12):self.action(str(i),'x'*2000+str(i),1)
        state=self.memory.execution_snapshot(TID);self.assertEqual(len(state['failures']),3)
        self.assertLess(len(self.memory.execution_instructions(state)),6000)
        self.assertEqual(len(self.memory.execution_snapshot(TID)['failures']),3)
    def test_invalid_record_latest_has_actionable_guidance(self):
        with self.assertRaisesRegex(ValueError,'history_checkpoint'):self.memory.read(TID,'latest')
    def test_75k_working_context_and_62k_compaction_leave_thinking_unlimited(self):
        settings={'model':core.MODEL,'context':256000,'model_contexts':{core.MODEL:256000},'history_mode':'memory','work_context':76800,
                  'backend':'vulkan','cpu_offload':False,'kv_cache_location':'auto','api_key':'test'}
        self.assertEqual(core.engine_limits(settings),(76800,63488))
        with patch.object(core,'load_settings',return_value=settings):args=core.model_args(core.MODEL,109568)
        self.assertEqual(args[args.index('--reasoning-budget')+1],'-1');self.assertEqual(args[args.index('-n')+1],'-1')

if __name__=='__main__':unittest.main()
