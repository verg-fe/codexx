"""End-to-end checks against the deployed model, not mocked model responses."""
import json
from pathlib import Path
import queue
import subprocess
import time
import traceback
import core

results = {'model': core.MODEL, 'context_target': 40960, 'checks': {}}
REPORT = core.ROOT / 'verification.json'

def record(name, value):
    results['checks'][name] = value
    REPORT.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
    print(name, json.dumps(value, ensure_ascii=False)[:1500], flush=True)

def start():
    core.prepare()
    p = core.start_model()
    deadline = time.monotonic() + 300
    while not core.server_ready():
        if p is not None and p.poll() is not None:
            raise RuntimeError('Model failed to load: read logs/model.log')
        if time.monotonic() > deadline:
            raise RuntimeError('Model startup timed out')
        time.sleep(2)
    props = core.api('/props')
    record('loaded', {'model': core.api('/v1/models')['data'][0]['id'],
        'generation': {k:v for k,v in props.get('default_generation_settings', {}).items()
                       if k in ['n_ctx', 'n_predict', 'temperature', 'top_p', 'top_k']},
        'total_slots': props.get('total_slots')})

def basic():
    t = time.monotonic()
    r = core.api('/v1/responses', {'model': core.MODEL,
        'input': '请只回复 LOCAL_OK，不添加任何其他内容。',
        'max_output_tokens': 256,
        'chat_template_kwargs': {'enable_thinking': False}}, timeout=300)
    text = ''.join(c.get('text', '') for i in r.get('output', []) for c in i.get('content', []))
    record('responses', {'ok': 'LOCAL_OK' in text, 'text': text[:1000],
                        'usage': r.get('usage'), 'seconds': round(time.monotonic()-t,2)})
    assert 'LOCAL_OK' in text, 'Responses endpoint did not produce the expected text'

def agent():
    project = core.ROOT / 'verification-project'
    project.mkdir(exist_ok=True)
    (project / 'math_utils.py').write_text('def clamp(value, low, high):\n    return min(low, max(high, value))\n', encoding='utf-8')
    (project / 'test_clamp.py').write_text('''import unittest
from math_utils import clamp
class ClampTest(unittest.TestCase):
    def test_boundaries(self):
        for value, expected in [(-1,0),(0,0),(3,3),(9,9),(12,9)]:
            self.assertEqual(clamp(value,0,9),expected)
if __name__ == '__main__': unittest.main()
''', encoding='utf-8')
    before = subprocess.run(['python', '-m', 'unittest', '-v'], cwd=project, capture_output=True,
                            creationflags=core.NO_WINDOW)
    assert before.returncode != 0
    events = queue.Queue()
    rpc = core.RpcClient(events.put)
    summaries = []
    try:
        thread = rpc.request('thread/start', {'cwd': str(project), 'approvalPolicy': 'never',
                    'sandbox': 'workspace-write'})['thread']['id']
        rpc.request('turn/start', {'threadId': thread, 'effort': 'low',
                    'input': [{'type': 'text', 'text': '请读取 math_utils.py，修复 clamp 的上下限逻辑错误，仅修改该函数。然后实际运行 python -m unittest -v，确认测试通过。用中文简要说明结果。'}]})
        deadline = time.monotonic() + 900
        while time.monotonic() < deadline:
            try:
                e = events.get(timeout=30)
            except queue.Empty:
                print('Waiting for agent generation...', flush=True)
                continue
            method = e.get('method', '')
            if 'id' in e and method:
                rpc.send({'id': e['id'], 'result': {'decision': 'decline'}})
            if method == 'item/completed':
                i = e['params']['item']
                if i.get('type') in ['commandExecution', 'fileChange', 'agentMessage']:
                    summaries.append(i)
                    print('agent event', i.get('type'), str(i.get('command', i.get('text', '')))[:180], flush=True)
            if method == 'turn/completed':
                if e['params']['turn'].get('error'):
                    raise RuntimeError(str(e['params']['turn']['error']))
                break
        else:
            raise RuntimeError('Coding task timed out')
        after = subprocess.run(['python', '-m', 'unittest', '-v'], cwd=project,
                       capture_output=True, text=True, encoding='utf-8', creationflags=core.NO_WINDOW)
        record('coding_tools', {'ok': after.returncode == 0,
              'commands': [i.get('command') for i in summaries if i.get('type') == 'commandExecution'],
              'file_changes': [i.get('changes') for i in summaries if i.get('type') == 'fileChange'],
              'test_output': after.stdout + after.stderr, 'thread_id': thread})
        assert after.returncode == 0, 'The agent failed to repair the intentionally broken function'
        assert any(i.get('type') == 'commandExecution' and 'unittest' in i.get('command','') for i in summaries), 'The model did not actually run tests'
        rpc.request('turn/start', {'threadId': thread, 'effort': 'low',
                    'input': [{'type':'text','text':'刚才修复的是哪个函数？一句话回答，不运行工具。'}]})
        followup = ''
        while True:
            e = events.get(timeout=180)
            if e.get('method') == 'item/agentMessage/delta':
                followup += e['params'].get('delta','')
            if e.get('method') == 'turn/completed':
                break
        record('conversation', {'ok': 'clamp' in followup, 'text': followup[:1200]})
        assert 'clamp' in followup
        from PIL import Image, ImageDraw
        image = Image.new('RGB', (384,384), 'white')
        ImageDraw.Draw(image).rectangle((64,64,320,320), fill='red')
        picture = project / 'vision_test.png'
        image.save(picture)
        rpc.request('turn/start', {'threadId': thread, 'effort':'low', 'input':[
            {'type':'text','text':'图片中央的正方形是什么颜色？只回答颜色。'},
            {'type':'localImage','path':str(picture)}]})
        visual = ''
        while True:
            e = events.get(timeout=180)
            if e.get('method') == 'item/agentMessage/delta':
                visual += e['params'].get('delta','')
            if e.get('method') == 'turn/completed':
                if e['params']['turn'].get('error'):
                    raise RuntimeError(str(e['params']['turn']['error']))
                break
        record('vision', {'ok': '红' in visual or 'red' in visual.lower(), 'text':visual[:1200]})
        assert '红' in visual or 'red' in visual.lower()
    finally:
        rpc.close()

def long_context():
    marker = 'LCTX-7F19-4060'
    beginning = '<|im_start|>user\n本条消息开始处的唯一验证代码为 ' + marker + '。\n以下为无关填充。\n'
    ending = '\n填充结束。请只复述消息开头的验证代码。<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n'
    # Construct a real 40K prompt with the model's tokenizer, never by character estimates.
    unit = 'filler block unrelated text.\n'
    lo, hi = 1, 20000
    best = None
    while lo <= hi:
        n = (lo+hi)//2
        prompt = beginning + unit*n + ending
        tokens = core.api('/tokenize', {'content': prompt, 'add_special': True})['tokens']
        if len(tokens) <= 40200:
            best = (prompt, len(tokens))
            lo = n + 1
        else:
            hi = n - 1
    assert best and 40000 <= best[1] <= 40200
    print('Long context prefill', best[1], 'tokens', flush=True)
    t = time.monotonic()
    response = core.api('/completion', {'prompt': best[0], 'n_predict': 128,
         'temperature': 0, 'cache_prompt': True, 'id_slot': 0}, timeout=1200)
    record('40k_context', {'ok': marker in response.get('content',''), 'input_tokens': best[1],
        'content': response.get('content','')[:1500], 'timings': response.get('timings'),
        'seconds': round(time.monotonic()-t, 2)})
    assert marker in response.get('content',''), '40K retrieval failed'
    t = time.monotonic()
    second = core.api('/completion', {'prompt': best[0], 'n_predict': 16,
        'temperature': 0, 'cache_prompt': True, 'id_slot': 0}, timeout=300)
    record('kv_reuse', {'timings': second.get('timings'),
                       'seconds': round(time.monotonic()-t, 2)})

if __name__ == '__main__':
    try:
        start()
        basic()
        agent()
        long_context()
        results['success'] = True
    except Exception as e:
        results['success'] = False
        results['error'] = str(e)
        print(traceback.format_exc(), flush=True)
        raise
    finally:
        REPORT.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
