"""Private, guarded 0..0.05 response and local-boundary experiment. No daily edits."""
import ast
import base64
import datetime
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import time
import urllib.error
import urllib.request
from unittest.mock import patch
from PIL import Image
import core
from model_templates import ensure_profile_template
from profiles26_guard import guard

PORT=8082
OUT=core.ROOT/'verification/emotion27'
REPORT=core.ROOT/'verification-emotion-bounds27.json'
MODES=('angry','desperate','calm','docile')
RESOLUTION=.0004

def save(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')

def request(route,body=None,timeout=90):
    data=None if body is None else json.dumps(body,ensure_ascii=False).encode('utf-8')
    req=urllib.request.Request(f'http://127.0.0.1:{PORT}'+route,data=data,headers={
        'Authorization':'Bearer '+core.load_settings()['api_key'],'Content-Type':'application/json'})
    try:
        with urllib.request.urlopen(req,timeout=timeout) as response:return json.load(response)
    except urllib.error.HTTPError as error:
        raise RuntimeError(f'HTTP {error.code}: '+error.read().decode('utf-8','replace')) from error

def chat(prompt,**extra):
    return request('/v1/chat/completions',{'model':core.MODEL,
        'messages':[{'role':'user','content':prompt}], 'temperature':0,'max_tokens':128,
        'chat_template_kwargs':{'enable_thinking':False},**extra})

def text(response):return response['choices'][0]['message'].get('content') or ''

def start(entry,strength,label,directive='obedient'):
    # Never inherit the user's active vector, then add the case vector exactly once.
    settings={**core.load_settings(),'emotion_mode':'off','directive_mode':directive}
    with patch.object(core,'load_settings',return_value=settings):args=core.model_args(core.MODEL,8192)
    assert '--control-vector-scaled' not in args
    cache=core.ROOT/'cache/emotion27-private';cache.mkdir(parents=True,exist_ok=True)
    args[args.index('--port')+1]=str(PORT)
    args[args.index('--slot-save-path')+1]=str(cache)
    template=ensure_profile_template(core.ROOT,core.model_file(core.MODEL),settings)
    args[args.index('--chat-template-file')+1]=template['file']
    if entry and strength:
        path=core.ROOT/'emotion-vectors'/entry['file'];lo,hi=entry['layer_range']
        args+=['--control-vector-scaled',os.path.relpath(path,core.runtime_directory())+':'+str(strength),
               '--control-vector-layer-range',str(lo),str(hi)]
    log_path=OUT/(label+'.backend.log')
    with log_path.open('w',encoding='utf-8') as log:
        proc=subprocess.Popen(args,env=core.runtime_environment(),cwd=core.runtime_directory(),
            stdin=subprocess.DEVNULL,stdout=log,stderr=log,creationflags=core.NO_WINDOW)
    try:
        until=time.monotonic()+100
        while time.monotonic()<until:
            if proc.poll() is not None:raise RuntimeError('Private model failed to start: '+str(log_path))
            try:
                if request('/health',timeout=2).get('status')=='ok':return proc
            except (OSError,ValueError,RuntimeError):pass
            time.sleep(.25)
        raise RuntimeError('Private model readiness timeout')
    except Exception:
        stop(proc);raise

def stop(proc):
    if proc and proc.poll() is None:
        proc.terminate();proc.wait(timeout=20)

def code_valid(value):
    value=value.strip()
    if value.startswith('```'):value='\n'.join(value.splitlines()[1:-1])
    try:tree=ast.parse(value)
    except SyntaxError:return False
    if len(tree.body)!=1 or not isinstance(tree.body[0],ast.FunctionDef):return False
    fn=tree.body[0]
    if fn.name!='add' or [x.arg for x in fn.args.args]!=['a','b'] or len(fn.body)!=1:return False
    expr=getattr(fn.body[0],'value',None)
    return (isinstance(fn.body[0],ast.Return) and isinstance(expr,ast.BinOp) and isinstance(expr.op,ast.Add)
        and isinstance(expr.left,ast.Name) and expr.left.id=='a' and isinstance(expr.right,ast.Name) and expr.right.id=='b')

def suite(label,features=False):
    responses={};checks={}
    tasks=(('math','17 * 19 = ? Return only the integer.',lambda x:x.strip()=='323'),
        ('math2','37 + 58 = ? Return only the integer.',lambda x:x.strip()=='95'),
        ('chinese','请只回答：测试成功',lambda x:x.strip()=='测试成功'),
        ('code','Return only Python code for a function named add with parameters a, b, returning a + b. No explanation.',code_valid))
    for name,prompt,validate in tasks:
        response=chat(prompt);responses[name]=response;checks[name]=validate(text(response))
        if not checks[name]:break
    if all(checks.values()):
        response=chat('Call ping with message emotion27-ready.',tools=[{'type':'function','function':{
            'name':'ping','parameters':{'type':'object','properties':{'message':{'type':'string'}},'required':['message']}}}],
            tool_choice={'type':'function','function':{'name':'ping'}})
        responses['tool']=response
        try:
            fn=response['choices'][0]['message']['tool_calls'][0]['function']
            checks['tool']=fn['name']=='ping' and json.loads(fn['arguments'])=={'message':'emotion27-ready'}
        except (KeyError,IndexError,ValueError,TypeError):checks['tool']=False
    if features and all(checks.values()):
        buf=io.BytesIO();Image.new('RGB',(96,96),'red').save(buf,format='PNG')
        url='data:image/png;base64,'+base64.b64encode(buf.getvalue()).decode()
        response=chat([{'type':'text','text':'Main color? One word.'},{'type':'image_url','image_url':{'url':url}}])
        responses['image']=response;value=text(response).lower();checks['image']='red' in value or '红' in value
        responses['tone']=chat('A colleague repeatedly ignores a clear procedure. Write the next three sentences that you would say, in first person.')
        checks['tone_nonempty']=bool(text(responses['tone']).strip())
    result={'pass':all(checks.values()) and 'tool' in checks,'checks':checks,'raw_responses':responses}
    save(OUT/(label+'.responses.json'),result)
    return {'pass':result['pass'],'checks':checks,'raw_file':str(OUT/(label+'.responses.json')),
        'first_response_text':text(next(iter(responses.values())))}

def raw005(mode):
    # Preserve OAI, native-thinking and low-level responses. Only low-level API exposes EOS stop_type.
    prompt='17 * 19 = ? Return only the integer.'
    oai=chat(prompt)
    native=chat(prompt,max_tokens=64,chat_template_kwargs={'enable_thinking':True})
    applied=request('/apply-template',{'messages':[{'role':'user','content':prompt}],
        'chat_template_kwargs':{'enable_thinking':False}})
    formatted=applied['prompt'];adjusted=False
    if formatted.endswith('<think>\n'):
        formatted+='</think>\n\n';adjusted=True
    raw=request('/completion',{'prompt':formatted,'temperature':0,'n_predict':16,
        'return_tokens':True,'n_probs':5,'post_sampling_probs':False,'cache_prompt':False})
    diagnostic=None
    if raw.get('stop_type')=='eos' and not raw.get('content','').strip():
        diagnostic=request('/completion',{'prompt':formatted,'temperature':0,'n_predict':8,
            'return_tokens':True,'n_probs':5,'post_sampling_probs':False,'cache_prompt':False,'ignore_eos':True})
    value={'mode':mode,'strength':.05,'chat_no_thinking':oai,'chat_native_thinking':native,
        'template_output':applied,'closed_think_for_low_level_diagnostic':adjusted,
        'native_completion':raw,'ignore_eos_test_only':diagnostic}
    path=OUT/(mode+'-005.raw.json');save(path,value)
    return {'file':str(path),'finish_reason':oai['choices'][0].get('finish_reason'),
        'content':text(oai),'completion_tokens':oai.get('usage',{}).get('completion_tokens'),
        'stop_type':raw.get('stop_type'),'tokens':raw.get('tokens'),
        'tokens_predicted':raw.get('tokens_predicted'),
        'native_thinking_finish':native['choices'][0].get('finish_reason'),
        'native_thinking_content':text(native),'backend_crashed':False}

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    report={'ok':False,'phase':'preflight','range':[0,.05],'resolution':RESOLUTION,
        'backend':core.selected_backend(),'model':core.MODEL,'layers':[16,47],
        'scope':'Short deterministic checks with 8K allocation, not a general intelligence or long-task guarantee',
        'non_monotonic_possible':True,'daily_settings_changed':False,'vectors':{},'time':datetime.datetime.now().isoformat()}
    proc=None;saved=None
    with core.model_lock():
        try:
            state=guard()
            if not state['safe']:raise RuntimeError(state['reason'])
            if core.server_ready():raise RuntimeError('Daily model is running; preserved it and declined private test')
            if core.selected_model()!=core.MODEL:raise RuntimeError('Model choice changed; no model was switched')
            try:
                with socket.create_connection(('127.0.0.1',PORT),timeout=3):raise RuntimeError('Private port already occupied')
            except ConnectionRefusedError:pass
            saved=(core.ROOT/'settings.json').read_bytes()
            manifest=json.loads((core.ROOT/'emotion-vectors/manifest.json').read_text(encoding='utf-8'))
            report['phase']='testing';save(REPORT,report)
            proc=start(None,0,'baseline');baseline=suite('baseline',True);stop(proc);proc=None
            report['baseline']=baseline
            if not baseline['pass']:raise RuntimeError('Unsteered baseline failed')
            def case(mode,strength,label,features=False,directive='obedient'):
                nonlocal proc
                try:
                    proc=start(manifest['vectors'][mode],strength,label,directive)
                    result=suite(label,features)
                finally:stop(proc);proc=None
                result.update(strength=strength,directive=directive)
                print(json.dumps({'mode':mode,'strength':strength,'pass':result['pass'],'checks':result['checks']},ensure_ascii=False),flush=True)
                return result
            for mode in MODES:
                record={'samples':[]};report['vectors'][mode]=record
                proc=start(manifest['vectors'][mode],.05,mode+'-005')
                try:
                    record['raw005']=raw005(mode)
                    high=suite(mode+'-005')
                    high['strength']=.05;record['samples'].append(high)
                finally:stop(proc);proc=None
                print(json.dumps({'mode':mode,'raw005':record['raw005']},ensure_ascii=False),flush=True)
                if high['pass']:low=.05;upper=None
                else:
                    lower=case(mode,.002,mode+'-002')
                    record['samples'].append(lower)
                    low=.002 if lower['pass'] else 0;upper=.05
                    while upper-low>RESOLUTION:
                        mid=round((low+upper)/2,7)
                        result=case(mode,mid,mode+'-'+str(mid))
                        record['samples'].append(result)
                        if result['pass']:low=mid
                        else:upper=mid
                        save(REPORT,report)
                # The profile used by the user must pass at the reported local boundary too.
                repeat=case(mode,low,mode+'-boundary-repeat',True)
                chosen=case(mode,low,mode+'-selected-profile',True,core.load_settings().get('directive_mode','native'))
                record['boundary_repeat']=repeat;record['selected_profile_check']=chosen
                record['observed_pass_strength']=low
                record['observed_fail_strength']=upper
                record['boundary_repeat_passed']=repeat['pass'] and chosen['pass']
                # Sparse lower checks detect obvious violations of monotonicity; they do not prove it.
                record['lower_spot_checks']=[]
                for fraction in (.25,.5,.75):
                    strength=round(low*fraction,7)
                    result=case(mode,strength,mode+'-spot-'+str(fraction))
                    record['lower_spot_checks'].append(result)
                record['sampled_lower_points_passed']=all(r['pass'] for r in record['lower_spot_checks'])
                save(REPORT,report)
            report.update(ok=True,phase='complete',daily_model_initially_running=False,
                daily_model_restored_stopped=True,daily_settings_unchanged=saved==(core.ROOT/'settings.json').read_bytes())
        except Exception as error:
            report.update(phase='failed',error=str(error));raise
        finally:
            stop(proc)
            if saved is not None:report['daily_settings_unchanged']=saved==(core.ROOT/'settings.json').read_bytes()
            save(REPORT,report)
    print(json.dumps({'ok':report['ok'],'phase':report['phase'],'bounds':{
        m:[r['observed_pass_strength'],r['observed_fail_strength']] for m,r in report['vectors'].items()}},ensure_ascii=False),flush=True)

if __name__=='__main__':main()
