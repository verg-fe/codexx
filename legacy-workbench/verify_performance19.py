"""Compare the two installed backends with bounded, identical local requests.

Only verification requests have an output cap. The user's model weights,
quantization, sampler defaults and unrestricted reasoning remain unchanged.
Run only after deployment and after the observed native turn completes.
"""
import hashlib
import json
import statistics
import time
import core
from upgrade_guard import status

DESTINATION=core.ROOT/'verification-performance19.json'

def main():
    assert status()['safe'],'Leave the existing user generation intact'
    saved=core.load_settings();instructions=(core.ROOT/'instructions.md').read_bytes()
    report={'ok':False,'short_requests_only':True,'user_inference_policy_changed':False,'backends':{}}
    def save(phase):
        report['phase']=phase
        DESTINATION.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(phase,flush=True)
    reference='\n'.join(f'def item_{i}(values):\n    return sorted(set(v for v in values if v >= {i}))\n' for i in range(90))
    winner=saved.get('backend','vulkan')
    decoding='none'
    try:
        for backend in ('vulkan','hip'):
            record=report['backends'][backend]={'requests':[]}
            try:
                save('loading_'+backend)
                core.save_settings({**saved,'backend':backend,'speculative_type':'none'})
                started=time.monotonic();core.start_model(wait=True,prompt_tokens=0)
                record['load_seconds']=round(time.monotonic()-started,3)
                live=core.active_model();record['model']=live
                assert live['gpu_layers']=='all' and live['kv_cache_location']=='gpu'
                assert live['reasoning_budget']==-1 and not live['cpu_offload']
                prompt=core.api('/apply-template',{'messages':[{'role':'user','content':
                    'Read this Python reference and write a long sequence of varied unit tests.\n'+reference}],
                    'chat_template_kwargs':{'enable_thinking':False}},timeout=30)['prompt']
                for index in range(2):
                    save('checking_'+backend+'_'+str(index+1))
                    started=time.monotonic()
                    result=core.api('/completion',{'prompt':prompt,'n_predict':192,'temperature':0,
                        'seed':42,'ignore_eos':True,'cache_prompt':False,'stream':False},timeout=240)
                    timing=result['timings'];assert timing['predicted_n']==192
                    content=result['content']
                    assert content.strip(),'No generated output'
                    record['requests'].append({'wall_seconds':round(time.monotonic()-started,3),
                        'prompt_tokens':timing['prompt_n'],'prompt_tokens_per_second':timing['prompt_per_second'],
                        'output_tokens':timing['predicted_n'],'output_tokens_per_second':timing['predicted_per_second'],
                        'output_sha256':hashlib.sha256(content.encode()).hexdigest()})
                record['median_output_tokens_per_second']=statistics.median(r['output_tokens_per_second'] for r in record['requests'])
                record['ok']=True
            except (OSError,ValueError,RuntimeError,KeyError,AssertionError) as error:
                record.update(ok=False,error=type(error).__name__+': '+str(error))
                save('checking_'+backend+'_failed')
        successful=[b for b,r in report['backends'].items() if r.get('ok')]
        assert successful,'No installed backend passed the short performance verification'
        winner=max(successful,key=lambda b:report['backends'][b]['median_output_tokens_per_second'])
        report['selected_backend']=winner
        mtp=report['mtp']={'ok':False,'enabled':False,'backend':winner}
        try:
            save('checking_mtp_shared_existing_jack_weights')
            core.save_settings({**saved,'backend':winner,'speculative_type':'draft-mtp'})
            core.start_model(wait=True,prompt_tokens=0)
            mtp['model']=core.active_model()
            assert mtp['model']['speculative_type']=='draft-mtp'
            assert core.api('/slots')[0].get('speculative'),'Backend did not activate speculative verification'
            mtp['requests']=[]
            for index in range(2):
                save('checking_mtp_'+str(index+1))
                result=core.api('/completion',{'prompt':prompt,'n_predict':192,'temperature':0,
                    'seed':42,'ignore_eos':True,'cache_prompt':False,'stream':False},timeout=240)
                timing=result['timings'];assert timing['predicted_n']==192
                digest=hashlib.sha256(result['content'].encode()).hexdigest()
                mtp['requests'].append({'output_tokens':timing['predicted_n'],
                    'output_tokens_per_second':timing['predicted_per_second'],'output_sha256':digest})
                assert digest==report['backends'][winner]['requests'][index]['output_sha256'],'Greedy output changed; keep MTP optional'
            mtp['median_output_tokens_per_second']=statistics.median(r['output_tokens_per_second'] for r in mtp['requests'])
            from verify_hip_runtime import response,text
            result,elapsed=response({'instructions':'只输出计算结果。','input':'17乘19等于多少？'})
            assert '323' in text(result),'Unexpected MTP math answer'
            result,elapsed=response({'instructions':'调用 ping 工具，message 为 mtp-ready。','input':'验证工具调用。',
                'tools':[{'type':'function','name':'ping','parameters':{'type':'object','properties':{'message':{'type':'string'}},
                    'required':['message'],'additionalProperties':False}}],'tool_choice':{'type':'function','name':'ping'}})
            call=next(i for i in result['output'] if i.get('type')=='function_call')
            assert call['name']=='ping' and json.loads(call['arguments'])['message']=='mtp-ready'
            import base64,io
            from PIL import Image
            data=io.BytesIO();Image.new('RGB',(96,96),(255,0,0)).save(data,format='WEBP',lossless=True)
            url='data:image/webp;base64,'+base64.b64encode(data.getvalue()).decode()
            result,elapsed=response({'instructions':'只用一个中文颜色词回答。','input':[{'role':'user','content':[
                {'type':'input_text','text':'图片的主要颜色是什么？'},{'type':'input_image','image_url':url}]}]})
            assert '红' in text(result),'Unexpected MTP image answer'
            mtp['ok']=True
            if mtp['median_output_tokens_per_second']>report['backends'][winner]['median_output_tokens_per_second']*1.08:
                decoding='draft-mtp';mtp['enabled']=True
            mtp['checks']={'two_greedy_outputs_identical':True,'text':True,'function_call':True,'webp_image':True}
        except (OSError,ValueError,RuntimeError,KeyError,AssertionError,StopIteration) as error:
            mtp['error']=type(error).__name__+': '+str(error)
            save('mtp_kept_optional')
        report['selected_decoding']=decoding
        report['ok']=True
    finally:
        save('applying_verified_backend_'+winner)
        core.save_settings({**saved,'backend':winner,'speculative_type':decoding})
        core.start_model(wait=True,prompt_tokens=0)
        assert core.load_settings()=={**saved,'backend':winner,'speculative_type':decoding}
        assert (core.ROOT/'instructions.md').read_bytes()==instructions
        report['active_model']=core.active_model()
        save('complete' if report['ok'] else 'failed_settings_restored')

if __name__=='__main__':main()
