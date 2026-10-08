"""Replay malformed arguments and verify recovery without executing learner code."""
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent / 'release51'))
import app
from gateway import fit_generation_to_window
from tool_call_recovery import diagnose_call, RecoveryBudget

tools = {'apply_patch': {'parameters': {'required': ['input']}}}
trace = Path('D:/LocalCodex/logs/generation/20261008T005037.902964Z-44e71428704b.jsonl')
raw = ''.join(e['delta'] for e in map(json.loads, trace.read_text(encoding='utf-8').splitlines())
              if e.get('event') == 'generated_delta' and e.get('channel') == 'tool_arguments')
assert diagnose_call({'name': 'apply_patch', 'arguments': raw}, tools)[0] == 'tool_arguments_incomplete'
assert diagnose_call({'name': 'apply_patch', 'arguments': '{}'}, tools)[0] == 'tool_arguments_missing'
assert diagnose_call({'name': 'unknown', 'arguments': '{}'}, tools)[0] == 'tool_unknown'
assert diagnose_call({'name': 'apply_patch', 'arguments': json.dumps({'input': '*** Begin Patch\n*** End Patch'})}, tools) is None

budget = RecoveryBudget()
state = {'thread_id': 'original', 'id': 'failure-1', 'code': 'tool_arguments_incomplete', 'reason': 'JSON incomplete'}
assert budget.plan('different', state) is None
assert budget.plan('original', state) == (0, 1)
assert budget.plan('original', state) is None
assert budget.plan('original', dict(state, id='failure-2')) == (0, 2)
assert budget.plan('original', dict(state, id='failure-3')) is None
budget.cancel()
assert budget.plan('original', dict(state, id='failure-4')) is None
budget.cancel(reset=True)
assert budget.plan('original', dict(state, id='failure-5')) == (2, 1)

requests = []
fake = SimpleNamespace(tool_recovery=budget, thread_id='original', busy=False, turn_id=None,
                       rpc=SimpleNamespace(request=lambda method, params: requests.append((method, params)) or {'turn': {'id': 'retry'}}),
                       input=SimpleNamespace(get=lambda *a: ''), message_buffers={}, artifact_task={'workdir': 'same-workdir'},
                       project=Path('original-project'), settings={}, effort=SimpleNamespace(get=lambda: '深入思考'),
                       workspace_store=SimpleNamespace(instructions=lambda state: ''), session_workspace=None,
                       sync_send_button=lambda: None, background=lambda work: work())
with patch.object(app, 'gateway_api', return_value={}), patch.object(app, 'memory_instructions', return_value=''), \
        patch.object(app, 'TaskArtifacts', return_value=SimpleNamespace(instructions=lambda thread: '')):
    app.App.retry_invalid_tool(fake, 'original', state, budget.ticket)
    assert len(requests) == 1 and requests[0][0] == 'turn/start'
    assert requests[0][1]['cwd'] == 'same-workdir' and requests[0][1]['threadId'] == 'original'
    assert '4000' in requests[0][1]['input'][0]['text']
    fake.busy=False;fake.turn_id=None
    budget.cancel()
    app.App.retry_invalid_tool(fake, 'original', state, budget.ticket-1)
    assert len(requests) == 1
    fake.input=SimpleNamespace(get=lambda *a: 'user message')
    app.App.retry_invalid_tool(fake, 'original', state, budget.ticket)
    assert len(requests) == 1

body={'max_output_tokens': 20480, 'reasoning_budget_tokens': 16384}
fit_generation_to_window(body, '/v1/responses', 93000, 87000)
assert body['max_output_tokens'] == 5744 and body['reasoning_budget_tokens'] == 1648
print('PASS: real truncated-call replay, classification, bounded/deduplicated retries, manual-stop cancellation, original cwd/thread, typed user input preservation, 93k context fitting.')
