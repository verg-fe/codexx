"""Exercise a real 100K context and repeated official Codex compaction on Windows."""
import ctypes
from ctypes import wintypes
import json
import queue
import subprocess
import threading
import time
import traceback
import core

REPORT = core.ROOT / 'verification-100k.json'
results = {'context_target': core.CONTEXT, 'compact_threshold': core.COMPACT,
           'auto_approve': True, 'checks': {}, 'memory_samples': []}

class ProcessMemory(ctypes.Structure):
    _fields_ = [('cb', wintypes.DWORD), ('PageFaultCount', wintypes.DWORD)] + [
        (name, ctypes.c_size_t) for name in ['PeakWorkingSetSize','WorkingSetSize',
        'QuotaPeakPagedPoolUsage','QuotaPagedPoolUsage','QuotaPeakNonPagedPoolUsage',
        'QuotaNonPagedPoolUsage','PagefileUsage','PeakPagefileUsage','PrivateUsage']]

kernel = ctypes.WinDLL('kernel32', use_last_error=True)
kernel.OpenProcess.restype = wintypes.HANDLE
kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel.CloseHandle.argtypes = [wintypes.HANDLE]
psapi = ctypes.WinDLL('psapi', use_last_error=True)
psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessMemory), wintypes.DWORD]

def memory(pid):
    handle = kernel.OpenProcess(0x410, False, int(pid))
    if not handle:
        return None
    try:
        info = ProcessMemory()
        info.cb = ctypes.sizeof(info)
        if not psapi.GetProcessMemoryInfo(handle, ctypes.byref(info), info.cb):
            return None
        return {'working_mib': round(info.WorkingSetSize / 1048576, 2),
                'private_mib': round(info.PrivateUsage / 1048576, 2)}
    finally:
        kernel.CloseHandle(handle)

def save():
    REPORT.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')

def snapshot(label, rpc=None):
    model_pid = int((core.ROOT/'model.pid').read_text())
    sample = {'label': label, 'model': memory(model_pid)}
    if rpc:
        sample['codex'] = memory(rpc.process.pid)
    results['memory_samples'].append(sample)
    save()
    print('Memory', label, json.dumps(sample), flush=True)
    return sample

def long_context():
    marker = 'CTX100K-8F2A-9070'
    beginning = '<|im_start|>user\n消息开头的唯一验证代码是 '+marker+'。\n'
    ending = '\n填充结束。只复述消息开头的验证代码。<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n'
    unit = 'filler block unrelated text.\n'
    lo, hi, best = 1, 25000, None
    while lo <= hi:
        n = (lo + hi) // 2
        prompt = beginning + unit*n + ending
        count = len(core.api('/tokenize', {'content': prompt, 'add_special': True})['tokens'])
        if count <= 101200:
            best = (prompt, count)
            lo = n+1
        else:
            hi = n-1
    assert best and 100000 <= best[1] <= 101200
    print('100K prefill', best[1], 'actual tokens', flush=True)
    snapshot('before_100k')
    t = time.monotonic()
    response = core.api('/completion', {'prompt':best[0], 'n_predict':128,
        'temperature':0, 'cache_prompt':True, 'id_slot':0}, timeout=1800)
    check = {'ok': marker in response.get('content',''), 'input_tokens':best[1],
             'content':response.get('content',''), 'timings':response.get('timings'),
             'seconds':round(time.monotonic()-t,2)}
    results['checks']['100k_context'] = check
    save()
    print('100K result', json.dumps(check,ensure_ascii=False), flush=True)
    assert check['ok'], 'Beginning-of-context retrieval failed'
    snapshot('after_100k')
    second = core.api('/completion', {'prompt':best[0], 'n_predict':32,
        'temperature':0, 'cache_prompt':True, 'id_slot':0}, timeout=300)
    results['checks']['kv_reuse'] = {'ok': second['timings'].get('cache_n',0) > 100000,
                                   'timings':second.get('timings')}
    save()
    assert results['checks']['kv_reuse']['ok'], 'Current-slot KV reuse was lost'

def run_until_done(events, rpc, compact=False):
    text, saw_compact, approvals = '', False, 0
    deadline = time.monotonic()+600
    while time.monotonic() < deadline:
        try:
            event = events.get(timeout=20)
        except queue.Empty:
            print('Waiting for', 'compaction' if compact else 'generation', flush=True)
            continue
        method, params = event.get('method',''), event.get('params',{})
        if 'id' in event and method:
            approvals += 1
            if method in ('item/commandExecution/requestApproval','item/fileChange/requestApproval'):
                rpc.send({'id':event['id'],'result':{'decision':'accept'}})
            else:
                raise RuntimeError('Unexpected server request '+method)
        if method == 'item/agentMessage/delta':
            text += params.get('delta','')
        if method == 'item/completed' and params.get('item',{}).get('type') == 'commandExecution':
            item = params['item']
            results.setdefault('executed_commands', []).append({
                'command':item.get('command'), 'exit_code':item.get('exitCode'),
                'output':item.get('aggregatedOutput','')[:3000]})
        if method == 'item/completed' and params.get('item',{}).get('type') == 'contextCompaction':
            saw_compact = True
        if method == 'thread/compacted':
            saw_compact = True
        if method == 'error' and not params.get('willRetry',False):
            raise RuntimeError(str(params.get('error',params)))
        if method == 'turn/completed':
            assert not params['turn'].get('error'), str(params['turn'].get('error'))
            assert not compact or saw_compact, 'No completed contextCompaction event'
            return text, approvals
    raise TimeoutError('Codex operation timed out')

def compaction():
    events = queue.Queue()
    rpc = core.RpcClient(events.put)
    rounds = []
    try:
        thread = rpc.request('thread/start', {'cwd':str(core.ROOT/'verification-project'),
            'approvalPolicy':'never', 'sandbox':'danger-full-access'})['thread']['id']
        results['thread_id'] = thread
        assert rpc.request('thread/loaded/list', {}) is not None
        for n in range(4):
            prompt = ('长期任务验证：项目函数名 clamp；任务编号 RAM-COMPACT-9070；'
                      '保留这两个事实。下面只是无关参考文本，不要执行工具。\n' +
                      'sample reference irrelevant text.\n'*1500 +
                      '\n只回复“已保留 clamp / RAM-COMPACT-9070”，不要解释。')
            rpc.request('turn/start', {'threadId':thread,'effort':'low',
                'input':[{'type':'text','text':prompt}]})
            run_until_done(events,rpc)
            before = snapshot(f'round_{n+1}_before',rpc)
            rpc.request('thread/compact/start', {'threadId':thread})
            run_until_done(events,rpc,compact=True)
            rpc.request('turn/start', {'threadId':thread,'effort':'low',
                'input':[{'type':'text','text':'刚才的函数名和任务编号是什么？只复述这两个，不运行工具。'}]})
            answer, approvals = run_until_done(events,rpc)
            assert 'clamp' in answer and 'RAM-COMPACT-9070' in answer, answer
            after = snapshot(f'round_{n+1}_after',rpc)
            rounds.append({'round':n+1, 'retained_task':True, 'approval_requests':approvals,
                           'before':before, 'after':after})
            results['checks']['compaction'] = {'ok':True,'rounds':rounds}
            save()
        # A real command must execute under never/full-access without client approval requests.
        rpc.request('turn/start', {'threadId':thread,'effort':'low', 'input':[{'type':'text',
            'text':'实际运行一个命令：python -c "print(\'AUTO_YES_OK\')"，报告输出，不要修改文件。'}]})
        text, approvals = run_until_done(events,rpc)
        assert 'AUTO_YES_OK' in text
        assert any(c.get('exit_code') == 0 and 'AUTO_YES_OK' in c.get('output','')
                   for c in results.get('executed_commands',[])), 'No successful actual command'
        assert approvals == 0, 'Unexpected approval popup request'
        results['checks']['auto_yes'] = {'ok':True,'approval_requests':approvals,'text':text}
        model_values = [r['after']['model']['private_mib'] for r in rounds]
        codex_values = [r['after']['codex']['private_mib'] for r in rounds]
        results['checks']['memory_plateau'] = {
            'model_private_mib':model_values, 'codex_private_mib':codex_values,
            'model_last_minus_second_mib':round(model_values[-1]-model_values[1],2),
            'codex_last_minus_second_mib':round(codex_values[-1]-codex_values[1],2)}
        rpc.request('thread/unsubscribe', {'threadId':thread})
        save()
    finally:
        rpc.close()

if __name__ == '__main__':
    try:
        deadline = time.monotonic()+180
        while not core.server_ready():
            assert time.monotonic()<deadline, 'Model startup timed out'
            time.sleep(2)
        props = core.api('/props')
        actual = props.get('default_generation_settings',{}).get('n_ctx')
        assert actual == core.CONTEXT, actual
        results['checks']['loaded'] = {'ok':True,'n_ctx':actual}
        long_context()
        compaction()
        results['success'] = True
    except Exception as error:
        results['success'] = False
        results['error'] = str(error)
        print(traceback.format_exc(),flush=True)
        raise
    finally:
        save()
