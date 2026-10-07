"""Compare the same short/50K input on private servers; restore native work."""
import json
import socket
import statistics
import subprocess
import time
import urllib.request
from pathlib import Path
from unittest.mock import patch
import core
import verify_kv20 as kv
from vision31_guard import guard
from profiles26_guard import process_alive

ROOT=core.ROOT
DIR=ROOT/'verification-project/decode34'
REPORT=ROOT/'verification-decode34.json'
PORT=8082

def request(route,body=None,timeout=240):
    req=urllib.request.Request(f'http://127.0.0.1:{PORT}'+route,
        data=None if body is None else json.dumps(body).encode(),headers={
            'Authorization':'Bearer '+core.load_settings()['api_key'],'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=timeout) as response:return json.load(response)

def main():
    (DIR/'cache').mkdir(parents=True,exist_ok=True)
    before=json.loads((DIR/'before.json').read_text(encoding='utf-8'))
    original=core.load_settings(); saved=(ROOT/'settings.json').read_bytes()
    previous=core.active_model(); process=None; stopped=False
    report={'phase':'preflight','cases':{},'restored':False,'selected_backend':original['backend'],
        'scope':'same weights, Q4 KV, 109568 allocation, 3600/50000 actual input, 128-token probes',
        'daily_thinking_cap_changed':False,'weights_changed':False,'sampling_changed':False}
    def save(phase):
        report['phase']=phase
        REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({'phase':phase},ensure_ascii=False),flush=True)
    save('preflight')
    assert before['native_terminal'] and before['gui_exited']
    with socket.socket() as sock:sock.bind(('127.0.0.1',PORT))
    try:
        with core.model_lock():
            state=guard()
            if not state['safe'] and state['reason']=='Inference remains active':
                latest,terminal,_=kv.native_state(Path(before['native_file']))
                assert latest==before['turn_id'] and terminal and not process_alive(before['gui_pid'])
                assert core.active_model()['pid']==before['active_model']['pid']
                assert json.loads((ROOT/'request-routing.json').read_text())['thread_id']==before['thread_id']
                core._stop_model();stopped=True;state=guard()
            assert state['safe'],state['reason']
            assert core.selected_model(original)==core.MODEL and not original.get('cpu_offload')
            core._stop_model();stopped=True
            shared_prompts={}
            for backend in ('vulkan','hip'):
                assert (ROOT/'settings.json').read_bytes()==saved,'User selection changed'
                case=report['cases'][backend]={'requests':[],'ok':False}
                save('loading_'+backend)
                logfile=DIR/(backend+'.log')
                settings={**original,'backend':backend}
                with patch.object(core,'load_settings',return_value=settings):
                    args=core.model_args(core.MODEL,109568)
                args[args.index('--port')+1]=str(PORT)
                args[args.index('--slot-save-path')+1]=str(DIR/'cache')
                try:
                    with logfile.open('w',encoding='utf-8') as log:
                        process=subprocess.Popen(args,cwd=core.runtime_directory(backend),
                            env=core.runtime_environment(backend),stdin=subprocess.DEVNULL,
                            stdout=log,stderr=log,creationflags=core.NO_WINDOW)
                    deadline=time.monotonic()+120
                    while True:
                        if process.poll() is not None:raise RuntimeError('Private engine exited: '+str(process.returncode))
                        try:
                            if request('/health',timeout=2).get('status')=='ok':break
                        except (OSError,ValueError):pass
                        if time.monotonic()>deadline:raise TimeoutError('Private engine not ready')
                        time.sleep(.3)
                    case['memory_loaded']=kv.memory(process.pid)
                    for target in (3600,50000):
                        save(f'{backend}_input_{target}')
                        if target not in shared_prompts:
                            text='\n'.join(f'def record_{i}(values): return sorted(v for v in values if v >= {i})' for i in range(3200))
                            raw=request('/apply-template',{'messages':[{'role':'user','content':
                                'Review this Python reference and discuss testing edge cases.\n'+text}],
                                'chat_template_kwargs':{'enable_thinking':True,'preserve_thinking':True}})['prompt']
                            tokens=request('/tokenize',{'content':raw,'add_special':False})['tokens']
                            # Fixed identical token arrays for both backends. Synthetic throughput only.
                            shared_prompts[target]=tokens[:target-8]+request('/tokenize',{
                                'content':'\nContinue reviewing:\n','add_special':False})['tokens']
                        rows=[]
                        for repeat in range(2):
                            value=request('/completion',{'prompt':shared_prompts[target],'n_predict':128,
                                'seed':42,'ignore_eos':True,'cache_prompt':True,'stream':False})
                            t=value['timings']; assert t['predicted_n']==128 and value['content'].strip()
                            row={'repeat':repeat+1,'input_tokens':len(shared_prompts[target]),
                                'prefill_tokens':t['prompt_n'],'cached_tokens':t.get('cache_n'),
                                'output_tokens':t['predicted_n'],'output_tps':t['predicted_per_second'],
                                'prefill_tps':t['prompt_per_second']}
                            rows.append(row);case['requests'].append(row);save(f'{backend}_{target}_repeat_{repeat+1}')
                        case[str(target)+'_median_tps']=statistics.median(r['output_tps'] for r in rows)
                        case[str(target)+'_memory']=kv.memory(process.pid)
                    save(backend+'_functional')
                    with patch.object(kv,'request',side_effect=request):case['functional']=kv.functions_check(True)
                    case['ok']=True
                except Exception as e:
                    case['error']=(type(e).__name__+': '+str(e)).replace(original['api_key'],'[redacted]')
                    case['log']=str(logfile)
                finally:
                    kv.stop(process);process=None;save(backend+'_complete')
            v=report['cases'].get('vulkan',{});h=report['cases'].get('hip',{})
            if v.get('ok') and h.get('ok'):
                report['hip_long_gain']=h['50000_median_tps']/v['50000_median_tps']-1
                if report['hip_long_gain']>.08 and (ROOT/'settings.json').read_bytes()==saved:
                    selected={**original,'backend':'hip'}
                    core.save_settings(selected)
                    report['selected_backend']='hip';report['backend_changed']=True
    except Exception as e:
        report['error']=(type(e).__name__+': '+str(e)).replace(original['api_key'],'[redacted]')
    finally:
        kv.stop(process)
        if stopped:
            save('restoring')
            try:
                with core.model_lock():
                    current=core.load_settings()
                    core._start_model(core.selected_model(current),previous['context'],True,previous['context_limit'])
                report['restored']=core.server_ready()
                report['restored_model']={k:core.active_model().get(k) for k in
                    ('model','backend','context','context_limit','kv_cache_location','gpu_layers','reasoning_budget')}
            except Exception as e:report['restore_error']=str(e).replace(original['api_key'],'[redacted]')
        if report['restored']:
            if not before['native_was_terminal']:
                (ROOT/'resume-after-moe32.json').write_text(json.dumps({'authorized_by_user':True,'consumed':False,
                    'thread_id':before['thread_id'],'prompt':'继续刚才因后端速度对照测试暂停的原任务。沿用当前项目、已有文件和全部原要求，从最新工具结果继续，不要重复已经成功的操作。'},ensure_ascii=False),encoding='utf-8')
            ui=ROOT/'app/MyCodex-work33/MyCodex.exe'
            flags=['--resume-after-update'] if not before['native_was_terminal'] else ['--show-model-options']
            report['ui_pid']=subprocess.Popen([str(ui),'--no-auto-model',*flags],creationflags=core.NO_WINDOW).pid
            report['resume_requested']=not before['native_was_terminal']
        save('complete' if report['restored'] else 'failed')
        print(json.dumps({k:report.get(k) for k in ('restored','selected_backend','error','restore_error')},ensure_ascii=False),flush=True)

if __name__=='__main__':main()
