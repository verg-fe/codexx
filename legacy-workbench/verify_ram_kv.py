"""Check real RAM/GPU placement with a short response, without a full-context benchmark."""
import json
import subprocess
import time
import core


def memory_snapshot(pid):
    pid=int(pid)
    script=(f'$taskModel=Get-Process -Id {pid}; '
        '$taskRows=Get-CimInstance Win32_PerfFormattedData_GPUPerformanceCounters_GPUProcessMemory '
        f'| Where-Object {{ $_.Name -match "^pid_{pid}_" }}; '
        '[pscustomobject]@{working_set=$taskModel.WorkingSet64;private_bytes=$taskModel.PrivateMemorySize64;'
        'dedicated_gpu=($taskRows | Measure-Object -Property DedicatedUsage -Sum).Sum;'
        'shared_gpu=($taskRows | Measure-Object -Property SharedUsage -Sum).Sum} | ConvertTo-Json -Compress')
    result=subprocess.run(['powershell.exe','-NoProfile','-Command',script],
        stdin=subprocess.DEVNULL,capture_output=True,text=True,encoding='utf-8',
        timeout=20,creationflags=core.NO_WINDOW)
    if result.returncode:
        raise RuntimeError('Could not inspect native model memory')
    return json.loads(result.stdout)


def verify():
    saved=json.loads(json.dumps(core.load_settings()))
    result={'ok':False,'short_response_only':True}
    report=core.ROOT/'verification-ram-kv.json'
    try:
        settings=json.loads(json.dumps(saved))
        settings['model']=core.MODEL
        settings['kv_cache_location']='auto'
        settings['cpu_offload']=False
        settings['model_contexts'][core.MODEL]=core.GPU_CONTEXT_LIMIT
        core.prepare(settings)
        core.start_model(wait=True)
        result['gpu_107k']=memory_snapshot(core.active_model()['pid'])
        report.write_text(json.dumps(result,indent=2),encoding='utf-8')
        settings['model_contexts'][core.MODEL]=core.MAX_CONTEXT
        core.prepare(settings)
        core.start_model(wait=True,full_context=True)
        props=core.api('/props')
        live=core.active_model()
        assert props['default_generation_settings']['n_ctx']==256000
        assert live['kv_cache_location']=='ram' and live['gpu_layers']=='all' and live['cpu_offload'] is False
        response=core.api('/completion',{'prompt':'<|im_start|>user\n17乘19等于多少？只给数字。<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n',
            'n_predict':64,'temperature':0,'cache_prompt':False,'id_slot':0},timeout=120)
        assert '323' in response.get('content',''), response.get('content')
        result['ram_250k']=memory_snapshot(live['pid'])
        result['context']=256000
        result['gpu_layers']='all'
        result['kv_cache_location']='ram'
        result['content']=response['content']
        result['timings']=response.get('timings',{})
        result['available_ram_mib']=core.available_ram_mib()
        # CPU cache is initialized in RAM; compare with the same GPU-only model.
        assert result['ram_250k']['working_set']>result['gpu_107k']['working_set']+2*1073741824, result
        assert result['ram_250k']['dedicated_gpu']>8*1073741824, result
        assert result['ram_250k']['dedicated_gpu']<result['gpu_107k']['dedicated_gpu'], result
        result['ok']=True
    except Exception as error:
        result['error']=str(error)
        raise
    finally:
        core.prepare(saved)
        core.start_model(wait=True,prompt_tokens=0)
        result['restored_context']=core.load_settings()['context']
        report.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return result


if __name__=='__main__':
    result=verify()
    previous_path=core.ROOT/'verification-visible-output.json'
    previous=json.loads(previous_path.read_text(encoding='utf-8'))
    assert previous['checks']['real_svg_request_has_visible_output_and_file']
    previous['initial_validation_issue']='Allocator messages are not printed at the backend default verbosity; verified RAM/GPU counters instead.'
    previous.pop('error',None)
    previous.pop('traceback',None)
    previous['ram_kv_250k']=result
    previous['checks']['250k_ram_kv_gpu_weights_short_response']=True
    previous['ok']=True
    previous['phase']='complete'
    previous_path.write_text(json.dumps(previous,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False),flush=True)
