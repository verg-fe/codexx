"""Regression checks based on actual stopped generation, with no model inference."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch
import json
import sys

sys.path.insert(0, str(Path(__file__).parent / 'release52'))
from generation_guard import InferenceWatch, guard_options
from generation_trace import GenerationTrace
from tool_call_recovery import RecoveryBudget, decode_patch_arguments, ToolCallFormatError
from gateway import adapt_event

trace = Path('D:/LocalCodex/logs/generation/20261008T032623.358979Z-7353d6cd9d7e.jsonl')
watch=InferenceWatch('unused','test',guard_options({}),Mock(),Mock())
watch.stop=Mock(side_effect=AssertionError('False guard stop'))
for line in trace.open(encoding='utf-8'):
    event=json.loads(line)
    if event.get('event')=='generated_delta' and event.get('channel')=='reasoning':
        watch.event({'type':'response.reasoning_text.delta','delta':event['delta']})
assert watch.warnings and not watch.stopped.is_set(), 'Actual repeated reasoning must warn only'
for i in range(1000):
    watch.event({'type':'response.reasoning_text.delta','delta':str(i)+'x'*180+'\n\n'})
assert len(watch.phrases)<=256
for kind in ('response.failed','response.incomplete'):
    watch.event({'type':kind,'response':{'error':{'code':'upstream_original'}}})
assert not watch.stop.called, 'Preserve upstream failure instead of replacing it'

for raw,code in (('{"input":"unfinished','tool_arguments_incomplete'),('{}','tool_arguments_missing'),('{"input":7}','tool_arguments_missing')):
    try:
        adapt_event({'type':'response.function_call_arguments.done','item_id':'patch','arguments':raw},{'apply_patch'},{'patch'})
    except ToolCallFormatError as error:
        assert error.code==code
    else:raise AssertionError('Malformed custom tool must not be emitted')
assert decode_patch_arguments('{"input":"line1\\nline2"}')=='line1\nline2'

budget=RecoveryBudget()
state={'thread_id':'same','id':'a','code':'tool_arguments_incomplete'}
assert budget.plan('same',state)==(0,1)
assert budget.plan('same',dict(state,id='b'))==(0,2)
assert budget.plan('same',dict(state,id='c')) is None
budget.success('other')
assert budget.plan('same',dict(state,id='c')) is None
budget.success('same')
assert budget.plan('same',dict(state,id='c'))==(0,1)
budget.cancel()
assert budget.plan('same',dict(state,id='d')) is None

with TemporaryDirectory() as directory:
    t=GenerationTrace(directory,{'thread_id':'test'})
    parts=['中','文','\n','😀']*1500
    for delta in parts:t.event({'type':'response.output_text.delta','item_id':'a','delta':delta})
    t.diagnostic({'code':'reasoning_repetition','count':3})
    t.event({'type':'response.completed','response':{'status':'completed'}})
    t.finish('completed',200)
    records=[json.loads(x) for x in t.path.read_text(encoding='utf-8').splitlines()]
    deltas=[x for x in records if x.get('event')=='generated_delta']
    assert ''.join(x['delta'] for x in deltas)==''.join(parts)
    assert sum(x['delta_count'] for x in deltas)==len(parts)
    assert len(deltas)<len(parts)//10
    assert records[-1]['upstream_terminal']=='response.completed'
    assert records[-1]['generated_characters']['text']==sum(map(len,parts))
    before=t.path.read_bytes();t.finish('ignored');assert before==t.path.read_bytes()
    print('Unicode log replay:',len(parts),'deltas ->',len(deltas),'records, exact content preserved')
print('PASS: actual false-stop replay, bounded diagnostics, upstream cause preservation, malformed native patch arguments, recovery reset and stop cancellation, batched Unicode logs')
