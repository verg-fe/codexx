"""Apply full model-layer GPU execution and check one short response, no long benchmark."""
import json
from pathlib import Path
import re
import subprocess
import time
import core

REPORT=core.ROOT/'verification-full-gpu.json'
result={'ok':False,'context':20480,'cpu_offload':False}
def save(phase):
    result['phase']=phase
    REPORT.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')

try:
    settings=core.load_settings()
    settings['cpu_offload']=False
    settings['model']=core.MODEL
    settings['model_contexts']={name:20480 for name in core.MODELS}
    core.prepare(settings)
    try:
        core.ensure_full_gpu_capacity(core.HUIHUI_MODEL,20480)
    except RuntimeError as error:
        result['huihui_gpu_only_limitation']=str(error)
    save('loading_full_gpu')
    core.start_model(core.MODEL,20480,wait=True)
    props=core.api('/props')
    assert props['default_generation_settings']['n_ctx']==20480
    assert Path(props['model_path'])==core.model_file(core.MODEL)
    live=core.active_model()
    assert live['gpu_layers']=='all' and live['cpu_offload'] is False
    result['gpu_layers']=live['gpu_layers']
    result['model_path']=props['model_path']
    # These fields come from the actual loaded backend, when exposed by its build.
    result['backend_gpu_info']={key:value for key,value in props.items() if 'gpu' in key or 'device' in key}
    save('checking_short_response')
    response=core.api('/completion',{'prompt':'<|im_start|>user\n计算17乘19。先给出结果，再用一句中文说明。<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n',
        'n_predict':64,'temperature':0,'cache_prompt':False,'id_slot':0},timeout=120)
    result['content']=response.get('content','')
    result['timings']=response.get('timings',{})
    assert '323' in result['content'], 'Short answer check failed: '+result['content']
    result['ok']=True
    save('complete')
    print(json.dumps(result,ensure_ascii=True),flush=True)
except Exception as error:
    result['error']=str(error)
    save('failed')
    raise
