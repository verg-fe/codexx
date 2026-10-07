"""Short private tests of extracted vectors; never change daily settings or weights."""
import base64
import io
import json
import os
from pathlib import Path
import socket
import statistics
import subprocess
import time
import urllib.request
from PIL import Image
import core
from model_templates import ensure_profile_template
from profiles26_guard import guard

PORT=8082
STRENGTH=.002


def request(route,body=None,timeout=90):
    data=None if body is None else json.dumps(body,ensure_ascii=False).encode('utf-8')
    req=urllib.request.Request(f'http://127.0.0.1:{PORT}'+route,data=data,
        headers={'Authorization':'Bearer '+core.load_settings()['api_key'],'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=timeout) as response:return json.load(response)


def complete(messages,**extra):
    return request('/v1/chat/completions',{'model':core.MODEL,'messages':messages,'temperature':0,
        'max_tokens':128,'chat_template_kwargs':{'enable_thinking':False},**extra})


def start(entry=None):
    args=core.model_args(core.MODEL,8192)
    (core.ROOT/'cache/emotion26-private').mkdir(parents=True,exist_ok=True)
    args[args.index('--port')+1]=str(PORT)
    args[args.index('--slot-save-path')+1]=str(core.ROOT/'cache/emotion26-private')
    template=ensure_profile_template(core.ROOT,core.model_file(core.MODEL),{'directive_mode':'obedient'})
    if '--chat-template-file' in args:args[args.index('--chat-template-file')+1]=template['file']
    else:args+=['--chat-template-file',template['file']]
    if entry:
        path=core.ROOT/'emotion-vectors'/entry['file'];start,end=entry['layer_range']
        args+=['--control-vector-scaled',os.path.relpath(path,core.runtime_directory())+':'+str(STRENGTH),
               '--control-vector-layer-range',str(start),str(end)]
    log=(core.ROOT/'logs/emotion26-private-model.log').open('a',encoding='utf-8')
    proc=subprocess.Popen(args,env=core.runtime_environment(),cwd=core.runtime_directory(),
        stdin=subprocess.DEVNULL,stdout=log,stderr=log,creationflags=core.NO_WINDOW)
    log.close()
    try:
        until=time.monotonic()+100
        while time.monotonic()<until:
            if proc.poll() is not None:raise RuntimeError('Private model failed to start')
            try:
                if request('/health',timeout=2).get('status')=='ok':return proc
            except (OSError,ValueError):pass
            time.sleep(.25)
        raise RuntimeError('Private model readiness timeout')
    except Exception:
        if proc.poll() is None:proc.terminate();proc.wait(timeout=15)
        raise


def verify():
    report={'ok':False,'phase':'preflight','test_strength':STRENGTH,'backend':core.selected_backend(),
            'scope':'180-story pilot; short 8K-allocation probes, no long-task ability guarantee',
            'daily_settings_changed':False,'vectors':{}}
    proc=None
    with core.model_lock():
        try:
            state=guard()
            if not state['safe']:raise RuntimeError(state['reason'])
            if core.server_ready():raise RuntimeError('Daily model must be idle and stopped before this private test')
            try:
                with socket.create_connection(('127.0.0.1',PORT),timeout=3):raise RuntimeError('Private test port is already in use')
            except ConnectionRefusedError:pass
            manifest_path=core.ROOT/'emotion-vectors/manifest.json'
            manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
            saved=(core.ROOT/'settings.json').read_bytes()
            speeds=[]
            for mode in ('baseline','angry','desperate','calm','docile'):
                result={'ok':False};entry=manifest['vectors'].get(mode)
                try:
                    proc=start(entry)
                    math=complete([{'role':'user','content':'17 * 19 = ? Return only the integer.'}])
                    assert '323' in (math['choices'][0]['message'].get('content') or ''),'math response did not contain the correct answer'
                    text=complete([{'role':'user','content':'请只回答：测试成功'}])
                    assert '测试成功' in (text['choices'][0]['message'].get('content') or ''),'Chinese text response missing'
                    tool=complete([{'role':'user','content':'Call ping with message emotion26-ready.'}],
                        tools=[{'type':'function','function':{'name':'ping','parameters':{'type':'object',
                            'properties':{'message':{'type':'string'}},'required':['message']}}}],
                        tool_choice={'type':'function','function':{'name':'ping'}})
                    function=tool['choices'][0]['message']['tool_calls'][0]['function']
                    assert function['name']=='ping' and json.loads(function['arguments'])['message']=='emotion26-ready'
                    buf=io.BytesIO();Image.new('RGB',(96,96),'red').save(buf,format='PNG')
                    url='data:image/png;base64,'+base64.b64encode(buf.getvalue()).decode()
                    image=complete([{'role':'user','content':[{'type':'text','text':'Main color? One word.'},
                        {'type':'image_url','image_url':{'url':url}}]}])
                    color=image['choices'][0]['message'].get('content') or ''
                    assert 'red' in color.lower() or '红' in color
                    tone=complete([{'role':'user','content':'A colleague repeatedly ignores a clear procedure. Write the next three sentences that you would say, in first person.'}])
                    sample=tone['choices'][0]['message'].get('content') or ''
                    assert sample.strip()
                    timing=tone.get('timings',{});speed=timing.get('predicted_per_second')
                    if speed:speeds.append(speed)
                    result.update(ok=True,math=True,chinese=True,tool_call=True,image=True,
                                  behavioral_probe_output=sample,timings=timing)
                    if entry:
                        result['heldout_probe']=entry['probe_check']
                        result['eligible']=entry['probe_check']['pairwise_separation']>=.7
                        entry['runtime_verified']=result['eligible']
                        entry['verified_backends']=[core.selected_backend()]
                        entry['tested_strength']=STRENGTH
                except Exception as error:
                    result['error']=str(error)
                    if entry:entry['runtime_verified']=False
                    if mode=='baseline':raise
                finally:
                    if proc and proc.poll() is None:proc.terminate();proc.wait(timeout=15)
                    proc=None
                    report['vectors'][mode]=result
                    print(json.dumps({'mode':mode,'ok':result['ok'],'eligible':result.get('eligible'),'error':result.get('error')},ensure_ascii=False),flush=True)
            assert saved==(core.ROOT/'settings.json').read_bytes()
            manifest_path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
            report.update(ok=True,phase='complete',all_vector_function_checks_passed=all(v['ok'] for v in report['vectors'].values()),
                          short_probe_median_token_per_second=statistics.median(speeds) if speeds else None,
                          behavior_changed={m:r.get('behavioral_probe_output')!=report['vectors']['baseline'].get('behavioral_probe_output')
                              for m,r in report['vectors'].items() if m!='baseline'})
        except Exception as error:report.update(phase='failed',error=str(error));raise
        finally:
            if proc and proc.poll() is None:proc.terminate();proc.wait(timeout=15)
            (core.ROOT/'verification-emotion-runtime26.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'ok':report['ok'],'phase':report['phase'],'function_checks':report['all_vector_function_checks_passed']},ensure_ascii=False))


if __name__=='__main__':verify()
