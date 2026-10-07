"""Bounded real-token context stress test with RAM monitoring and durable results."""
import ctypes
from ctypes import wintypes
import json
import threading
import time
import traceback
import core
from verify_upgrade import memory

REPORT = core.ROOT / 'context-limit-tests.json'

class MemoryStatus(ctypes.Structure):
    _fields_=[('dwLength',wintypes.DWORD),('dwMemoryLoad',wintypes.DWORD)] + [
        (name,ctypes.c_ulonglong) for name in ['ullTotalPhys','ullAvailPhys','ullTotalPageFile',
        'ullAvailPageFile','ullTotalVirtual','ullAvailVirtual','ullAvailExtendedVirtual']]

def available_mib():
    state=MemoryStatus()
    state.dwLength=ctypes.sizeof(state)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(state))
    return state.ullAvailPhys/1048576

def make_prompt(target):
    markers=['EDGE-BEGIN-A7F9','EDGE-MIDDLE-B2C8','EDGE-END-C4E1']
    start='<|im_start|>user\nRemember three codes. BEGIN='+markers[0]+'\n'
    middle='\nMIDDLE='+markers[1]+'\n'
    end='\nEND='+markers[2]+'. Reply with all three codes only.\n<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n'
    unit='reference filler unrelated text.\n'
    def build(n): return start+unit*(n//2)+middle+unit*(n-n//2)+end
    unit_tokens=len(core.api('/tokenize',{'content':unit,'add_special':False},timeout=30)['tokens'])
    lo,hi,best=1,target//max(1,unit_tokens)+64,None
    while len(core.api('/tokenize',{'content':build(hi),'add_special':True},timeout=30)['tokens'])<=target:
        hi*=2
    while lo<=hi:
        n=(lo+hi)//2
        prompt=build(n)
        count=len(core.api('/tokenize',{'content':prompt,'add_special':True},timeout=30)['tokens'])
        if count<=target:
            best=(prompt,count)
            lo=n+1
        else: hi=n-1
    assert best and target-20 <= best[1] <= target
    return best,markers

class ExistingModel:
    def __init__(self,pid): self.pid=int(pid)
    def poll(self): return None if core.owned_process(self.pid) else 0
    def terminate(self): core.owned_process(self.pid,terminate=True)
    def wait(self,timeout=10):
        deadline=time.monotonic()+timeout
        while self.poll() is None:
            if time.monotonic()>deadline: raise TimeoutError('Owned model did not exit')
            time.sleep(0.1)

def test(name,context,probe=False,reuse=False):
    current=core.active_model()
    reuse=bool(reuse and current.get('model')==name and current.get('context')==context and
        current.get('pid') and core.owned_process(current['pid']) and core.server_ready())
    if not reuse: core.stop_model()
    (core.ROOT/'logs'/'context-test-progress.json').unlink(missing_ok=True)
    record={'model':name,'context':context,'probe_only':probe,'ok':False,'samples':[],
            'gpu_layers':core.gpu_layers(name,context),'cache_dtype':'q4_0','backend':'vulkan',
            'ram_reserve_mib':3072,'probe_request_headroom_mib':256 if probe else 0,
            'mmap':False,'reused_loaded_weights':reuse}
    running=threading.Event()
    running.set()
    proc=ExistingModel(current['pid']) if reuse else core.start_model(name,context)
    if reuse:
        assert not any(slot.get('is_processing') for slot in core.api('/slots'))
        record['erased_probe_cache']=core.api('/slots/0?action=erase',{},timeout=30)
    def watch():
        low=0
        while running.is_set():
            free=available_mib()
            record['samples'].append({'elapsed':round(time.monotonic()-t0,1),
                                     'available_ram_mib':round(free,1),'process':memory(proc.pid) or {}})
            low=low+1 if free<record['ram_reserve_mib'] else 0
            if low>=3:
                record['stopped_for_ram']=True
                proc.terminate()
                proc.wait(timeout=10)
                return
            running.wait(0)  # Sampling does not retain requests or model data.
            time.sleep(3)
    t0=time.monotonic()
    watcher=threading.Thread(target=watch,daemon=True)
    watcher.start()
    try:
        deadline=time.monotonic()+1200
        while not core.server_ready():
            if proc.poll() is not None: raise RuntimeError('Model exited during startup')
            if time.monotonic()>deadline: raise TimeoutError('Startup exceeded 20 minutes')
            time.sleep(1)
        props=core.api('/props')
        record['allocated_context']=props['default_generation_settings']['n_ctx']
        # YaRN windows can report one fewer token after backend rounding.
        assert context-1 <= record['allocated_context'] < context + 256
        record['usable_context']=min(context, record['allocated_context'])
        record['startup_seconds']=round(time.monotonic()-t0,2)
        print(name,context,'loaded',record['startup_seconds'],'s',flush=True)
        if probe:
            response=core.api('/completion',{'prompt':'<|im_start|>user\nReply OK.<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n',
                'n_predict':16,'temperature':0,'cache_prompt':True,'id_slot':0},timeout=300)
            record['short_prompt_timings']=response.get('timings')
            reused=core.api('/completion',{'prompt':'<|im_start|>user\nReply OK.<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n',
                'n_predict':16,'temperature':0,'cache_prompt':True,'id_slot':0},timeout=300)
            record['short_kv_reuse']=reused.get('timings')
            record['samples'].append({'elapsed':round(time.monotonic()-t0,1),
                'available_ram_mib':round(available_mib(),1),'process':memory(proc.pid) or {}})
            if min(x['available_ram_mib'] for x in record['samples'])<record['ram_reserve_mib']+record['probe_request_headroom_mib']:
                record['below_stable_reserve']=True
                raise MemoryError('Stable RAM reserve plus request headroom not met after checkpoint allocation')
            record['allocation_ok']=True
            # Allocation alone never raises the user-facing verified slider limit.
            return record
        (prompt,count),markers=make_prompt(record['usable_context']-1024)
        record['actual_input_tokens']=count
        print('FULL CONTEXT',name,count,'tokens',flush=True)
        began=time.monotonic()
        done=threading.Event()
        def progress():
            while not done.wait(25):
                try:
                    slot=core.api('/slots')[0]
                    processed=slot.get('n_prompt_tokens_processed',0)
                    record['progress_tokens']=processed
                    REPORT_PROGRESS=core.ROOT/'logs'/'context-test-progress.json'
                    REPORT_PROGRESS.write_text(json.dumps({'model':name,'target':count,'processed':processed,
                        'elapsed':round(time.monotonic()-began),'available_ram_mib':round(available_mib())}),encoding='utf-8')
                    print('Context progress',name,processed,'/',count,'elapsed',round(time.monotonic()-began),'s',flush=True)
                except (OSError,ValueError,IndexError): pass
        threading.Thread(target=progress,daemon=True).start()
        try:
            response=core.api('/completion',{'prompt':prompt,'n_predict':128,'temperature':0,
                'cache_prompt':True,'id_slot':0},timeout=64800)
        finally:
            done.set()
        record['seconds']=round(time.monotonic()-began,2)
        record['content']=response.get('content','')
        record['timings']=response.get('timings')
        assert record['timings'].get('cache_n',0)<100, 'Full input unexpectedly reused old history'
        assert all(marker in record['content'] for marker in markers), record['content']
        second=core.api('/completion',{'prompt':prompt,'n_predict':32,'temperature':0,
            'cache_prompt':True,'id_slot':0},timeout=600)
        record['kv_reuse']=second.get('timings')
        assert record['kv_reuse'].get('cache_n',0)>count-100
        assert not record.get('stopped_for_ram')
        if min(x['available_ram_mib'] for x in record['samples'])<record['ram_reserve_mib']:
            record['below_stable_reserve']=True
            raise MemoryError('Stable RAM reserve not met during full-context test')
        record['ok']=True
        return record
    except Exception as error:
        record['error']=str(error)
        record['traceback']=traceback.format_exc()
        return record
    finally:
        running.clear()
        watcher.join(timeout=4)
        record['minimum_available_ram_mib']=min(x['available_ram_mib'] for x in record['samples'])
        print('CONTEXT TEST RESULT',name,context,record.get('ok'),record.get('error',''),flush=True)

def save_result(record):
    data=json.loads(REPORT.read_text(encoding='utf-8')) if REPORT.exists() else {'tests':[]}
    data['tests'].append(record)
    temporary=REPORT.with_suffix('.tmp')
    temporary.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    temporary.replace(REPORT)
    if record['ok'] and not record.get('probe_only'):
        path=core.ROOT/'context-limits.json'
        limits=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'models':{}}
        old=limits['models'].get(record['model'],{}).get('max_context',0)
        usable=record.get('usable_context',record['context'])
        if usable>=old:
            limits['models'][record['model']]={'max_context':usable,'verified':True,
                'input_tokens':record['actual_input_tokens'],'report':str(REPORT)}
            temporary=path.with_suffix('.tmp')
            temporary.write_text(json.dumps(limits,ensure_ascii=False,indent=2),encoding='utf-8')
            temporary.replace(path)

if __name__=='__main__':
    import sys
    name=sys.argv[1] if len(sys.argv)>1 else core.HUIHUI_MODEL
    context=int(sys.argv[2]) if len(sys.argv)>2 else core.NATIVE_CONTEXT
    save_result(test(name,context,'--probe' in sys.argv))
