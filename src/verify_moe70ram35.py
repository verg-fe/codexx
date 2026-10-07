"""Private 150K MoE4All retry, always restore the user's runtime and dialogue."""
from datetime import datetime
import json
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
import core
from moe4all_backend import arguments as base_arguments,resources,progress
def arguments(*a,**kw):
    return base_arguments(*a,**kw)+['--set','kv.dynamic=false','--set','kv.overflow=true','--set','kv.overflow_vram_mb=512']
from vision31_guard import guard
from verify_kv20 import native_state
from profiles26_guard import process_alive

ROOT=core.ROOT
CONTEXT_K=int(sys.argv[1]) if len(sys.argv)>1 else 150
assert 8<=CONTEXT_K<=256,'Private test context must be between 8K and 256K'
DIRECTORY=ROOT/f'verification-project/moe70ram35'
REPORT=ROOT/f'verification-moe70ram35.json'
PORT=8082
CONTEXT=CONTEXT_K*1024
BATCHES=(int(sys.argv[2]),) if len(sys.argv)>2 else (64,16)
assert all(x in (4,8,16,32,64,128) for x in BATCHES)

def call(route,body=None,timeout=5):
    request=urllib.request.Request(f'http://127.0.0.1:{PORT}'+route,
        data=None if body is None else json.dumps(body).encode(),headers={
            'Authorization':'Bearer '+core.load_settings()['api_key'],'Content-Type':'application/json'})
    with urllib.request.urlopen(request,timeout=timeout) as response:
        return {'healthy':True} if route=='/health' else json.load(response)

def stop(process):
    if process and process.poll() is None:
        process.terminate()
        try:process.wait(timeout=10)
        except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)

def main():
    before=json.loads((DIRECTORY/'before.json').read_text(encoding='utf-8'))
    original=core.load_settings();saved=(ROOT/'settings.json').read_bytes();previous=core.active_model()
    assert before['native_terminal'] and before['gui_exited']
    report={'phase':'preflight','context_tokens':CONTEXT,'context_label':f'{CONTEXT_K}K','units':'1K = 1024 tokens',
        'backend':'MoE4All 0.9.0','model':core.selected_model(original),'cases':[],
        'allocation_and_short_output_only':True,'long_context_filled':False,'daily_settings_changed':False,
        'restored':False,'success':False,'original_thread':before['thread_id']}
    process=None;model_stopped=False
    def save():REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    save()
    try:
        with socket.socket() as check:check.bind(('127.0.0.1',PORT))
        with core.model_lock():
            state=guard()
            if not state['safe'] and state['reason']=='Inference remains active':
                # The native interrupt is terminal, but llama's ongoing prefill
                # may not notice the disconnected client until decode starts.
                # Stop only the exact model owned by this authorized receipt.
                latest,ended,_=native_state(Path(before['native_file']))
                routing=json.loads((ROOT/'request-routing.json').read_text())
                assert latest==before['turn_id'] and ended and not process_alive(before['gui_pid'])
                assert routing.get('thread_id')==before['thread_id']
                assert core.active_model().get('pid')==before['active_model']['pid']
                core._stop_model();model_stopped=True
                report['cancelled_prefill_cleaned_up']=True
                state=guard()
            assert state['safe'],state['reason']
            assert core.selected_model(original)==core.MODEL,'Preserve a changed model choice'
            assert core.selected_backend(original)=='vulkan','Preserve a changed backend choice'
            core._stop_model();model_stopped=True
            engine=core.runtime_executable('moe4all');env=core.runtime_environment('moe4all')
            # The child inherits no unsafe VRAM-guard override.
            env.pop('INFR_NO_VRAM_GUARD',None)
            env['RUST_LOG']='warn,infr_server=info'
            report['resources_after_release']=resources(engine,engine.parent,env,core.NO_WINDOW)
            for batch in BATCHES:
                case_root=DIRECTORY/f'batch-{batch}';case_root.mkdir(exist_ok=True)
                logfile=case_root/'engine.log'
                case={'ubatch':batch,'vision_configured':False,'kv_k':'q8_0','kv_v':'q8_0',
                    'dynamic_kv':False,'ram_overflow':True,'kv_vram_reserve_mib':1024,'context_tokens':CONTEXT,'ready':False,'success':False}
                report['cases'].append(case);report['phase']=f'loading_batch_{batch}';save()
                args=arguments(case_root,engine,{**original,'moe_ssd_cache':False},
                    core.model_file(core.MODEL),None,CONTEXT)
                args[args.index('--addr')+1]=f'127.0.0.1:{PORT}'
                args+=['--ubatch',str(batch)]
                start=time.monotonic()
                with logfile.open('w',encoding='utf-8') as log:
                    process=subprocess.Popen(args,cwd=engine.parent,env=env,
                        stdin=subprocess.DEVNULL,stdout=log,stderr=log,creationflags=core.NO_WINDOW)
                try:
                    until=time.monotonic()+100
                    while time.monotonic()<until:
                        if process.poll() is not None:raise RuntimeError('Engine exited '+str(process.returncode))
                        try:
                            if call('/health',timeout=2)['healthy']:case['ready']=True;break
                        except (OSError,ValueError):pass
                        time.sleep(.25)
                    assert case['ready'],'MoE4All startup timed out'
                    case['load_seconds']=round(time.monotonic()-start,2)
                    report['phase']='short_generation';save()
                    value=call('/v1/chat/completions',{'model':core.MODEL,
                        'messages':[{'role':'user','content':'请用中文列出20条简短的Python代码规范，每条一句。'}],
                        'max_tokens':32,'stream':False},timeout=180)
                    message=value['choices'][0]['message']
                    assert (message.get('content') or message.get('reasoning_content') or '').strip(),'No model output'
                    case['short_usage']=value.get('usage');case['short_timings']=value.get('timings')
                    case['model_token_metrics']=progress(logfile)
                    case['success']=True;report['success']=True
                except Exception as error:
                    case['error']=str(error).replace(original['api_key'],'[redacted]')
                    case['engine_log']=str(logfile)
                    case['log_tail']=logfile.read_text(encoding='utf-8',errors='replace')[-3500:].replace(original['api_key'],'[redacted]')
                    case['exit_code']=process.poll()
                finally:
                    stop(process);process=None;case['elapsed_seconds']=round(time.monotonic()-start,2);save()
                    print(json.dumps({'context':CONTEXT,'ubatch':batch,'ready':case['ready'],
                        'success':case['success'],'error':case.get('error')},ensure_ascii=False),flush=True)
                if case['success']:break
            report['phase']='restoring';save()
            current=core.load_settings()
            if (ROOT/'settings.json').read_bytes()==saved:
                core._start_model(previous['model'],previous['context'],True,previous['context_limit'])
            else:
                report['user_choice_changed']=True
                name=core.selected_model(current)
                core._start_model(name,core.runtime_context_for(current,name),True,core.context_for(current,name))
            report['restored']=core.server_ready();assert report['restored'],'The daily model did not recover'
            report['restored_model']={k:core.active_model().get(k) for k in ('model','backend','context','context_limit','kv_cache_location','reasoning_budget','gpu_layers')}
            report['daily_settings_changed']=(ROOT/'settings.json').read_bytes()!=saved
            report['phase']='complete';save()
    except Exception as error:
        report['error']=str(error).replace(original['api_key'],'[redacted]');report['phase']='failed';save()
        if model_stopped and not report['restored']:
            try:
                stop(process);process=None
                with core.model_lock():
                    if not core.server_ready():
                        current=core.load_settings();name=core.selected_model(current)
                        context=previous['context'] if current==original else core.runtime_context_for(current,name)
                        core._start_model(name,context,True,core.context_for(current,name))
                    report['restored']=core.server_ready()
            except Exception as recovery:report['recovery_error']=str(recovery).replace(original['api_key'],'[redacted]')
            save()
    finally:
        stop(process)
        if report['restored']:
            resume=ROOT/'resume-after-moe32.json'
            if resume.exists():shutil.copy2(resume,DIRECTORY/'resume-before.json')
            if not before['native_was_terminal']:
                resume.write_text(json.dumps({'authorized_by_user':True,'consumed':False,'thread_id':before['thread_id'],
                    'prompt':'继续刚才因 MoE4All 后端测试暂停的原任务，沿用当前项目、已有实现和全部原要求。读取最新工具结果，从中断处继续；保留已经写入的文件，不要重新开始或重复已经成功的操作。'},ensure_ascii=False),encoding='utf-8')
            desktop=ROOT/'app/MyCodex-work33/MyCodex.exe'
            assert desktop.exists()
            flags=['--resume-after-update'] if not before['native_was_terminal'] else ['--show-model-options']
            ui=subprocess.Popen([str(desktop),'--no-auto-model',*flags],creationflags=core.NO_WINDOW)
            report['ui_pid']=ui.pid;report['resume_requested']=not before['native_was_terminal']
        report['time']=datetime.now().astimezone().isoformat();save()
    print(json.dumps({k:report.get(k) for k in ('success','restored','resume_requested','phase','ui_pid','error')},ensure_ascii=False),flush=True)

if __name__=='__main__':main()
