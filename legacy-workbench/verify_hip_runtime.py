"""Verify the private HIP server with short requests, then restore Vulkan.

Output caps apply only to these verification requests, never user settings.
No maximum-context benchmark is performed.
"""
import base64
import io
import json
import time
import urllib.request
from PIL import Image
import core

DESTINATION = core.ROOT/'verification-hip18.json'

def health():
    request=urllib.request.Request('http://127.0.0.1:8081/health',headers={
        'Authorization':'Bearer '+core.load_settings()['api_key']})
    with urllib.request.urlopen(request,timeout=5) as response:
        return json.load(response)

def response(body):
    headers={'Authorization':'Bearer '+core.load_settings()['api_key'],'Content-Type':'application/json'}
    request=urllib.request.Request('http://127.0.0.1:8081/v1/responses',headers=headers,
        data=json.dumps({'model':core.MODEL,'reasoning':{'effort':'none'},
                        'chat_template_kwargs':{'enable_thinking':False},
                        'max_output_tokens':256,'temperature':0,'stream':True,**body}).encode())
    events=[]; started=time.monotonic()
    with urllib.request.urlopen(request,timeout=180) as result:
        for line in result:
            if line.startswith(b'data:'):
                payload=line[5:].strip()
                if payload!=b'[DONE]':events.append(json.loads(payload))
    terminal=next((e for e in reversed(events) if e.get('type')=='response.completed'),None)
    if terminal is None:
        raise AssertionError('HIP response did not complete: '+str([e.get('type') for e in events[-3:]]))
    return terminal['response'], round(time.monotonic()-started,3)

def text(result):
    return ''.join(b.get('text','') for item in result.get('output',[]) for b in item.get('content',[])
                   if b.get('type')=='output_text')

def main():
    saved=core.load_settings(); instructions=(core.ROOT/'instructions.md').read_bytes()
    report={'ok':False,'phase':'starting','short_requests_only':True,'checks':{}}
    def save(phase):
        report['phase']=phase
        DESTINATION.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(phase,flush=True)
    error=None
    try:
        assert health()['adapter_version']==core.ADAPTER_VERSION
        assert not any(slot.get('is_processing') for slot in core.api('/slots'))
        save('loading_hip_gpu_109568')
        core.prepare({**saved,'backend':'hip'})
        started=time.monotonic()
        core.start_model(wait=True,prompt_tokens=0)
        report['load_seconds']=round(time.monotonic()-started,3)
        live=core.active_model();report['hip_model']=live
        assert live['backend']=='hip' and live['context']==109568
        assert live['gpu_layers']=='all' and not live['cpu_offload']
        assert live['kv_cache_location']=='gpu' and live['reasoning_budget']==-1
        assert core.owned_process(live['pid'])
        report['checks']['hip_gpu_load']=True
        save('checking_hip_text')
        result,elapsed=response({'instructions':'只输出计算结果。','input':'17乘19等于多少？'})
        answer=text(result);report['text']={'answer':answer,'seconds':elapsed,'usage':result.get('usage')}
        assert '323' in answer, 'Unexpected math answer'
        report['checks']['text']=True
        save('checking_hip_function_call')
        result,elapsed=response({'instructions':'请调用 ping 工具，参数 message 为 hip-ready。',
            'input':'调用工具验证。','tools':[{'type':'function','name':'ping',
                'description':'A verification function.','parameters':{'type':'object',
                'properties':{'message':{'type':'string'}},'required':['message'],'additionalProperties':False}}],
            'tool_choice':{'type':'function','name':'ping'}})
        call=next(item for item in result['output'] if item.get('type')=='function_call')
        assert call['name']=='ping' and json.loads(call['arguments'])['message']=='hip-ready'
        report['function']={'name':call['name'],'arguments':call['arguments'],'seconds':elapsed}
        report['checks']['function_call']=True
        save('checking_hip_webp_image')
        image=Image.new('RGB',(96,96),(255,0,0)); buffer=io.BytesIO();image.save(buffer,format='WEBP',lossless=True)
        url='data:image/webp;base64,'+base64.b64encode(buffer.getvalue()).decode()
        result,elapsed=response({'instructions':'只用一个中文颜色词回答。',
            'input':[{'role':'user','content':[{'type':'input_text','text':'图片的主要颜色是什么？'},
                                              {'type':'input_image','image_url':url}]}]})
        answer=text(result);report['image']={'answer':answer,'seconds':elapsed}
        assert '红' in answer, 'Unexpected image answer'
        report['checks']['webp_image']=True
        report['checks']['gateway_version']=health()['adapter_version']==core.ADAPTER_VERSION
    except Exception as exception:
        error=exception;report['error']=type(exception).__name__+': '+str(exception)
        save('hip_verification_failed')
    finally:
        save('restoring_original_backend')
        core.prepare(saved)
        core.start_model(wait=True,prompt_tokens=0)
        report['restored_model']=core.active_model()
        report['checks']['settings_preserved']=core.load_settings()==saved
        report['checks']['instructions_preserved']=(core.ROOT/'instructions.md').read_bytes()==instructions
        report['checks']['restored_backend']=report['restored_model'].get('backend','vulkan')==saved.get('backend','vulkan')
        report['ok']=error is None and all(report['checks'].values())
        save('complete' if report['ok'] else 'failed_with_original_backend_restored')
    if error:raise error

if __name__=='__main__':main()
