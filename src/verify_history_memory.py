import hashlib
import json
from pathlib import Path
import subprocess
import sqlite3
import sys
import tempfile
import tomllib
import tracemalloc
import unittest
from unittest.mock import patch

import core
from history_memory import HistoryMemory, memory_instructions, archive_thread_id, CHUNK_CHARS

ONE='11111111-1111-4111-8111-111111111111'
TWO='22222222-2222-4222-8222-222222222222'

def line(text,role='user'):
    return (json.dumps({'timestamp':'2026-10-03T00:00:00Z','type':'response_item',
        'payload':{'type':'message','role':role,'content':[{'type':'input_text','text':text}]}},
        ensure_ascii=False)+'\n').encode()

class MemoryChecks(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.root=Path(self.temporary.name)
        self.memory=HistoryMemory(self.root)
    def tearDown(self):self.temporary.cleanup()
    def rollout(self,thread_id,data):
        p=self.root/'codex-home/sessions'/('rollout-'+thread_id+'.jsonl');p.parent.mkdir(parents=True,exist_ok=True)
        p.write_bytes(data);return p
    def trace(self,data):
        p=self.root/'logs/generation/test.jsonl';p.parent.mkdir(parents=True,exist_ok=True)
        p.write_bytes(data);self.memory.register_source(ONE,p,'trace');return p
    def test_chinese_search_is_scoped_and_original_is_unchanged(self):
        p=self.rollout(ONE,line('鹈鹕文件保存在 pelican-cycling.svg')+line('SYSTEM_SECRET','developer'))
        self.rollout(TWO,line('鹈鹕另一个会话的资料'))
        digest=hashlib.sha256(p.read_bytes()).hexdigest()
        result=self.memory.search(ONE,'鹈鹕')
        self.assertEqual(len(result['results']),1);self.assertIn('pelican',result['results'][0]['text'])
        self.assertFalse(self.memory.search(ONE,'SYSTEM_SECRET')['results'])
        self.assertEqual(hashlib.sha256(p.read_bytes()).hexdigest(),digest)
    def test_full_read_paginates_across_chunks_without_missing_characters(self):
        text='开头\n'+('XYZ汉字'*4000)+'END_MARKER'
        self.rollout(ONE,line(text));r=self.memory.search(ONE,'END_MARKER')['results'][0]
        parts=[];offset=0
        while True:
            page=self.memory.read(ONE,r['record_id'],offset,3500);parts.append(page['text'])
            if page['next_offset'] is None:break
            offset=page['next_offset']
        self.assertEqual(''.join(parts),text)
    def test_partial_utf8_record_is_retried_without_duplicates(self):
        data=line('中文新记录 UNIQUE');p=self.rollout(ONE,data[:-5])
        self.assertFalse(self.memory.search(ONE,'UNIQUE')['results'])
        with p.open('ab') as f:f.write(data[-5:])
        self.assertEqual(len(self.memory.search(ONE,'UNIQUE')['results']),1)
        self.assertEqual(len(self.memory.search(ONE,'UNIQUE')['results']),1)
    def test_keyword_crossing_chunk_boundary_is_searchable(self):
        self.rollout(ONE,line('x'*(CHUNK_CHARS-5)+'CROSS_BOUNDARY_MARKER'+'tail'))
        self.assertTrue(self.memory.search(ONE,'CROSS_BOUNDARY_MARKER')['results'])
    def test_search_treats_sql_and_fts_syntax_as_literal_data(self):
        self.rollout(ONE,line('literal a_b 100% OR "quote"'))
        self.assertTrue(self.memory.search(ONE,'a_b')['results'])
        self.assertFalse(self.memory.search(ONE,'a%b')['results'])
        self.memory.search(ONE,'" OR x');self.memory.search(ONE,"'; DROP TABLE chunks; --")
        self.assertTrue(self.memory.search(ONE,'literal')['results'])
    def test_deleted_threads_are_hidden_and_restore_reenables_read(self):
        self.rollout(ONE,line('restore-marker'));self.memory.search(ONE,'restore-marker')
        trash=self.root/'conversations/deleted/index.json';trash.parent.mkdir(parents=True)
        trash.write_text(json.dumps([{'session':{'id':ONE}}]))
        with self.assertRaisesRegex(ValueError,'删除'):self.memory.search(ONE,'restore-marker')
        trash.write_text('[]');self.assertTrue(self.memory.search(ONE,'restore-marker')['results'])
    def test_archive_cannot_escape_private_root_or_change_thread_owner(self):
        outside=self.root/'outside.jsonl';outside.write_bytes(line('x'))
        with self.assertRaises(ValueError):self.memory.register_source(ONE,outside,'rollout')
        p=self.rollout(ONE,line('x'));self.memory.register_source(ONE,p,'rollout')
        with self.assertRaises(ValueError):self.memory.register_source(TWO,p,'rollout')
    def test_checkpoint_keeps_previous_versions_and_native_compaction(self):
        p=self.rollout(ONE,line('task'))
        with p.open('ab') as f:f.write((json.dumps({'type':'compacted','payload':{'message':'NATIVE_SUMMARY'}})+'\n').encode())
        self.memory.checkpoint(ONE,'FIRST_STATE');self.memory.checkpoint(ONE,'LATEST_STATE')
        state=self.memory.checkpoint(ONE)
        self.assertEqual(state['checkpoint']['state'],'LATEST_STATE')
        self.assertEqual(state['latest_compaction']['text'],'NATIVE_SUMMARY')
        self.assertTrue(self.memory.search(ONE,'FIRST_STATE')['results'])
    def test_generated_reasoning_is_opt_in_and_snapshot_replaces_old_text(self):
        base={'channel':'reasoning','item_id':'r','content_index':0}
        p=self.trace((json.dumps({**base,'event':'generated_delta','delta':'OLD_THOUGHT'})+'\n').encode())
        self.assertFalse(self.memory.search(ONE,'OLD_THOUGHT')['results'])
        self.assertTrue(self.memory.search(ONE,'OLD_THOUGHT',include_reasoning=True)['results'])
        with p.open('ab') as f:f.write((json.dumps({**base,'event':'stream_snapshot','text':'REVISED'})+'\n').encode())
        self.assertFalse(self.memory.search(ONE,'OLD_THOUGHT',include_reasoning=True)['results'])
        self.assertTrue(self.memory.search(ONE,'REVISED',include_reasoning=True)['results'])
    def test_large_generated_trace_does_not_accumulate_output_in_python_ram(self):
        p=self.trace(b'');row={'event':'generated_delta','channel':'text','item_id':'m','content_index':0,'delta':'x'*1000}
        encoded=(json.dumps(row)+'\n').encode()
        with p.open('ab') as f:
            for _ in range(12000):f.write(encoded)
            row['delta']='END_MARKER';f.write((json.dumps(row)+'\n').encode())
        tracemalloc.start()
        result=self.memory.search(ONE,'END_MARKER');current,peak=tracemalloc.get_traced_memory();tracemalloc.stop()
        self.assertTrue(result['results']);self.assertLess(peak,4*1024*1024)
        with self.memory.connect() as db:
            self.assertLess(db.execute('SELECT count(*) FROM chunks').fetchone()[0],6000)
        print('History index 12 MB generated text; Python peak bytes:',peak)
    def test_working_context_is_separate_from_physical_cache_and_thinking_budget(self):
        settings={'model':core.MODEL,'model_contexts':{core.MODEL:256000},'history_mode':'memory','work_context':32768,
                  'kv_cache_location':'auto','cpu_offload':False,'api_key':'test'}
        self.assertEqual(core.engine_limits(settings),(32768,24576))
        self.assertEqual(core.context_for(settings,core.MODEL),256000)
        self.assertEqual(core.runtime_context_for(settings,core.MODEL,12000,current={}),109568)
        with patch.object(core,'load_settings',return_value=settings):args=core.model_args(core.MODEL,109568)
        self.assertEqual(args[args.index('--reasoning-budget')+1],'-1')
        self.assertEqual(args[args.index('-n')+1],'-1')
        self.assertEqual(core.engine_limits({**settings,'history_mode':'full'}),(256000,223232))
    def test_private_mcp_config_is_valid_and_preserves_original_instructions(self):
        settings={'model':core.MODEL,'context':256000,'project':str(self.root),'api_key':'test',
                  'model_contexts':{core.MODEL:256000},'history_mode':'memory','work_context':32768}
        original=core.INSTRUCTIONS
        with patch.object(core,'ROOT',self.root),patch.object(core.Path,'home',return_value=self.root/'no-user-home'):
            core.prepare(settings)
        config=tomllib.loads((self.root/'codex-home/config.toml').read_text())
        self.assertEqual(config['model_context_window'],32768)
        self.assertEqual(config['model_auto_compact_token_limit'],24576)
        self.assertEqual(config['mcp_servers']['local_history']['command'],sys.executable)
        self.assertEqual((self.root/'instructions.md').read_text(),original)
        self.assertEqual(archive_thread_id(memory_instructions(ONE)),ONE)
    def test_stdio_mcp_unicode_and_error_response(self):
        self.rollout(ONE,line('鹈鹕'))
        commands=[{'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2024-11-05'}},
            {'jsonrpc':'2.0','id':2,'method':'tools/list'},
            {'jsonrpc':'2.0','id':3,'method':'tools/call','params':{'name':'history_search','arguments':{'thread_id':ONE,'query':'鹈鹕'}}},
            {'jsonrpc':'2.0','id':4,'method':'tools/call','params':{'name':'history_read','arguments':{'thread_id':ONE,'record_id':'../bad'}}}]
        data=''.join(json.dumps(c,ensure_ascii=False)+'\n' for c in commands).encode()
        result=subprocess.run([sys.executable,'history_memory.py','--history-root',str(self.root)],input=data,capture_output=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stderr)
        responses=[json.loads(r) for r in result.stdout.splitlines()]
        self.assertEqual(len(responses),4)
        self.assertFalse(responses[2]['result']['isError']);self.assertTrue(responses[3]['result']['isError'])
    def test_native_index_connection_is_closed_after_lookup(self):
        rollout=self.rollout(ONE,line('native-index-marker'))
        state=self.root/'codex-home/state_5.sqlite'
        db=sqlite3.connect(state)
        db.execute('CREATE TABLE threads(id TEXT,rollout_path TEXT)')
        db.execute('INSERT INTO threads VALUES(?,?)',(ONE,str(rollout)))
        db.commit();db.close()
        self.assertEqual(self.memory.find_rollout(ONE),rollout.resolve())
        renamed=state.with_suffix('.closed')
        state.rename(renamed);renamed.rename(state)
    def test_large_checkpoint_returns_a_bounded_page_and_exact_remainder(self):
        state='任务目标；已确认约束；下一步验证。'*500
        result=self.memory.checkpoint(ONE,state)['checkpoint']
        self.assertLessEqual(len(result['state']),1500)
        complete=result['state'];offset=result['next_offset']
        while offset is not None:
            page=self.memory.read(ONE,result['record_id'],offset)
            complete+=page['text'];offset=page['next_offset']
        self.assertEqual(complete,state)
    def test_performance_scheduling_preserves_inference_precision_and_budgets(self):
        settings={'model':core.MODEL,'backend':'vulkan','cpu_offload':False,
                  'kv_cache_location':'auto','api_key':'test'}
        with patch.object(core,'load_settings',return_value=settings):normal=core.model_args(core.MODEL,109568)
        with patch.object(core,'load_settings',return_value={**settings,'performance_mode':'max'}):fast=core.model_args(core.MODEL,109568)
        self.assertEqual(fast[:len(normal)],normal)
        self.assertEqual(fast[fast.index('-tb')+1],'6')
        self.assertEqual(fast[fast.index('--prio')+1],'1')
    def test_mtp_only_predicts_for_jack_and_preserves_target_policy(self):
        settings={'model':core.MODEL,'backend':'vulkan','cpu_offload':False,'kv_cache_location':'auto','api_key':'test'}
        with patch.object(core,'load_settings',return_value=settings):normal=core.model_args(core.MODEL,109568)
        candidate={**settings,'speculative_type':'draft-mtp'}
        with patch.object(core,'load_settings',return_value=candidate):mtp=core.model_args(core.MODEL,109568)
        expected=list(normal);expected[expected.index('--spec-type')+1]='draft-mtp'
        self.assertEqual(mtp[:-4],expected)
        self.assertEqual(core.selected_decoding(candidate,core.HUIHUI_MODEL),'none')
        self.assertEqual(mtp[mtp.index('-n')+1],'-1')
        self.assertNotIn('--spec-synth-rates',mtp);self.assertNotIn('--spec-synth-len',mtp)

if __name__=='__main__':unittest.main(verbosity=2)
