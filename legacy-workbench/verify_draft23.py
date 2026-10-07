"""Verify real file locks, streamed drafts, compaction handoff and original draft recovery."""
import json
from pathlib import Path
import re
import tempfile
import unittest

import gateway
from generation_trace import GenerationTrace
from history_memory import HistoryMemory, memory_instructions
from task_artifacts import DraftStream, FileLocks, TaskArtifacts

TID='01a0ff82-f328-7dc0-806a-7ed0532e015f'


class DraftProtection(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        self.project=self.root/'project';self.project.mkdir()
        self.store=TaskArtifacts(self.root/'data')
        self.handles=[]

    def tearDown(self):
        for lock in self.handles:lock.close()
        self.tmp.cleanup()

    def begin(self,prompt):
        state,lock=self.store.begin(TID,self.project,prompt)
        self.handles.append(lock)
        return state,lock

    def test_actual_windows_lock_denies_read_and_write_then_releases(self):
        old=self.project/'old.svg';old.write_text('<svg/>')
        state,lock=self.begin('画一只鹈鹕 SVG 动画')
        with self.assertRaises(PermissionError):old.read_text()
        with self.assertRaises(PermissionError):old.write_text('overwritten')
        lock.close();self.assertEqual(old.read_text(),'<svg/>')

    def test_new_workdir_no_old_artifact_normal_source_remains_readable(self):
        (self.project/'main.py').write_text('source')
        (self.project/'gen_pelican.py').write_text('older root generator')
        d=self.project/'model-bench-task';d.mkdir();(d/'gen_pelican.py').write_text('old generator')
        state,_=self.begin('创建鹈鹕骑车 SVG')
        self.assertFalse((Path(state['workdir'])/'model-bench-task').exists())
        self.assertEqual((self.project/'main.py').read_text(),'source')
        with self.assertRaises(PermissionError):(d/'gen_pelican.py').read_text()
        with self.assertRaises(PermissionError):(self.project/'gen_pelican.py').read_text()

    def test_existing_edit_keeps_project_cwd(self):
        old=self.project/'pelican.svg';old.write_text('existing')
        state,lock=self.begin('修改现有 pelican.svg 的背景')
        self.assertEqual(state['workdir'],str(self.project.resolve()))
        self.assertEqual(lock.paths,[]);self.assertEqual(old.read_text(),'existing')

    def test_continuation_reuses_own_work_and_drafts(self):
        old=self.project/'old.svg';old.write_text('old')
        state,lock=self.begin('创建 SVG 动画');lock.close();self.store.finish(TID)
        own=Path(state['workdir'])/'own.svg';own.write_text('own')
        again,_=self.begin('继续完成')
        self.assertEqual(state['task_id'],again['task_id'])
        self.assertEqual(state['workdir'],again['workdir'])
        self.assertEqual(own.read_text(),'own')
        with self.assertRaises(PermissionError):old.read_text()

    def test_explicit_user_image_reference_remains_readable(self):
        old=self.project/'old.svg';old.write_text('old')
        ref=self.project/'reference.png';ref.write_bytes(b'user reference')
        state,lock=self.store.begin(TID,self.project,'根据图片创建 SVG 动画',[str(ref)])
        self.handles.append(lock)
        self.assertEqual(ref.read_bytes(),b'user reference')
        with self.assertRaises(PermissionError):old.read_text()

    def test_stream_split_fences_unicode_and_partial_persist_without_execution(self):
        state,_=self.begin('创建 SVG 动画')
        stream=DraftStream(state['draft_directory'],'123456789abc')
        text='解释\n```python\nraise RuntimeError("不应被执行")\n```\n```svg\n<svg>不完整'
        for char in text:stream.feed(('reasoning','r',0),char)
        stream.close()
        records=self.store.list(TID)['drafts']
        self.assertEqual(len(records),2);self.assertTrue(records[0]['complete']);self.assertFalse(records[1]['complete'])
        self.assertIn('不应被执行',self.store.read(TID,records[0]['id'])['text'])
        self.assertEqual(self.store.read(TID,records[1]['id'])['text'],'<svg>不完整')

    def test_long_line_keeps_memory_bounded_and_preserves_code(self):
        state,_=self.begin('创建 SVG 动画');stream=DraftStream(state['draft_directory'],'123456789abc')
        stream.feed('r','```python\n');content='x'*120000
        for at in range(0,len(content),173):stream.feed('r',content[at:at+173])
        self.assertLess(len(stream.states['r']['line']),8193)
        stream.feed('r','\n```\n');stream.close()
        record=self.store.list(TID)['drafts'][0]
        path=Path(state['draft_directory'])/'123456789abc'/record['file']
        self.assertEqual(path.read_text(),content+'\n')

    def test_previous_task_id_cannot_read_current_task_draft(self):
        state,lock=self.begin('创建 SVG 动画');stream=DraftStream(state['draft_directory'],'123456789abc')
        stream.feed('r','```python\nx=1\n```\n');stream.close();lock.close()
        self.begin('再画另一只鸟的 SVG')
        with self.assertRaises(OSError):self.store.read(TID,'123456789abc-0000')

    def test_draft_pages_keep_earlier_blocks_and_order_by_time_not_random_uuid(self):
        state,_=self.begin('创建 SVG 动画')
        earlier=DraftStream(state['draft_directory'],'ffffffffffff')
        earlier.feed('r',''.join(f'```python\nx={n}\n```\n' for n in range(45)));earlier.close()
        later=DraftStream(state['draft_directory'],'000000000001')
        later.feed('r','```python\nlatest=1\n```\n');later.close()
        newest=self.store.list(TID)
        self.assertEqual(newest['drafts'][-1]['id'],'000000000001-0000')
        self.assertEqual(newest['total_drafts'],46);self.assertEqual(newest['next_offset'],40)
        older=self.store.list(TID,offset=newest['next_offset'])
        self.assertEqual(len(older['drafts']),6);self.assertIsNone(older['next_offset'])
        self.assertEqual(older['drafts'][0]['id'],'ffffffffffff-0000')
        self.assertEqual(self.store.read(TID,older['drafts'][0]['id'])['text'],'x=0\n')

    def test_compaction_request_gets_exact_current_task_draft_pointer(self):
        state,_=self.begin('画 SVG 动画');stream=DraftStream(state['draft_directory'],'123456789abc')
        stream.feed('r','```python\nx=1\n```\n');stream.close()
        body={'instructions':memory_instructions(TID),'input':[{'role':'user','content':'compaction'}]}
        attached=gateway.attach_task_state(body,self.store.root)
        self.assertEqual(attached['task_id'],state['task_id'])
        self.assertIn('123456789abc-0000',body['instructions']);self.assertIn('draft_read',body['instructions'])
        memory=HistoryMemory(self.store.root)
        self.assertEqual(memory.call('draft_read',{'thread_id':TID,'draft_id':'123456789abc-0000'})['text'],'x=1\n')

    def test_generation_trace_wires_drafts_without_duplicating_done_text(self):
        state,_=self.begin('画 SVG 动画')
        trace=GenerationTrace(self.root/'logs',{'thread_id':TID,'draft_directory':state['draft_directory']})
        text='```python\nx=1\n```\n'
        trace.event({'type':'response.reasoning_text.delta','item_id':'r','delta':text})
        trace.event({'type':'response.reasoning_text.done','item_id':'r','text':text})
        trace.finish('complete')
        self.assertEqual(len(self.store.list(TID)['drafts']),1)
        self.assertIsNone(trace.drafts)

    def test_real_lost_pelican_generator_blocks_are_saved_verbatim(self):
        source=Path(r'D:\LocalCodex\logs\generation\20261003T020610.111694Z-a3df05a2b30a.jsonl')
        state,_=self.begin('画 SVG 动画')
        stream=DraftStream(state['draft_directory'],'123456789abc');parts=[]
        with source.open(encoding='utf-8') as file:
            for line in file:
                event=json.loads(line)
                if event.get('event')=='generated_delta' and event.get('channel')=='reasoning':
                    stream.feed('r',event['delta']);parts.append(event['delta'])
        stream.close()
        original=list(re.finditer(r'```([^\n]*)\n([\s\S]*?)```',''.join(parts)))
        records=self.store.list(TID)['drafts']
        self.assertEqual(len(records),31)
        for index in [23,24]:
            record=records[index];self.assertTrue(record['complete'])
            path=Path(state['draft_directory'])/'123456789abc'/record['file']
            self.assertEqual(path.read_text(),original[index].group(2))


if __name__=='__main__':unittest.main(verbosity=2)
