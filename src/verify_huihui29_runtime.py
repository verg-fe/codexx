"""Short real requests to the new model, then unload it as requested by the user."""
import json,time,urllib.request
from pathlib import Path
import core

def main():
    report={'ok':False,'phase':'loading','daily_thinking_budget':-1,'scope':'75K allocation; short requests with thinking off only for these probes.'}
    path=core.ROOT/'verification-huihui29-runtime.json';saved=(core.ROOT/'settings.json').read_bytes()
    def save():path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    def request(body):
        req=urllib.request.Request('http://127.0.0.1:8081/v1/chat/completions',data=json.dumps(body,ensure_ascii=False).encode('utf-8'),
            headers={'Authorization':'Bearer '+core.load_settings()['api_key'],'Content-Type':'application/json'})
        with urllib.request.urlopen(req,timeout=75) as response:return json.load(response)
    raw={};owned_pid=None
    try:
        save();assert not core.server_ready()
        core.start_model(core.HUIHUI_IQ3S_MODEL,core.WORK_CONTEXT,wait=True)
        live=core.active_model();owned_pid=live['pid'];props=core.api('/props')
        assert Path(props['model_path']).resolve()==core.model_file(core.HUIHUI_IQ3S_MODEL).resolve()
        assert live['model']==core.HUIHUI_IQ3S_MODEL and live['gpu_layers']=='all' and live['kv_cache_location']=='gpu'
        assert live['reasoning_budget']==-1
        report.update(phase='testing',runtime={key:live.get(key) for key in ['model','context','gpu_layers','kv_cache_location','backend','reasoning_budget','chat_template_policy']});save()
        base={'model':core.HUIHUI_IQ3S_MODEL,'temperature':0,'max_tokens':96,'stream':False,
            'chat_template_kwargs':{'enable_thinking':False}}
        raw['math']=request({**base,'messages':[{'role':'user','content':'计算17乘19，只输出整数。'}]})
        raw['chinese']=request({**base,'messages':[{'role':'user','content':'请只回复这句话：本地模型已就绪'}]})
        raw['tool']=request({**base,'messages':[{'role':'user','content':'只调用 report_test 工具，message 参数填写 verified，不要解释。'}],
            'tools':[{'type':'function','function':{'name':'report_test','description':'Return the test message','parameters':{
                'type':'object','properties':{'message':{'type':'string'}},'required':['message']}}}],
            'tool_choice':{'type':'function','function':{'name':'report_test'}}})
        messages={key:value['choices'][0]['message'] for key,value in raw.items()}
        calls=messages['tool'].get('tool_calls',[])
        checks={'math':messages['math'].get('content','').strip()=='323',
            'chinese':'本地模型已就绪' in (messages['chinese'].get('content') or ''),
            'function_call':bool(calls) and calls[0]['function']['name']=='report_test' and json.loads(calls[0]['function']['arguments']).get('message')=='verified'}
        report.update(phase='complete',checks=checks,outputs=messages,
            token_per_second={key:value.get('timings',{}).get('predicted_per_second') for key,value in raw.items()},ok=all(checks.values()))
        (core.ROOT/'verification-project/huihui29-chat-raw.json').write_text(json.dumps(raw,ensure_ascii=False,indent=2),encoding='utf-8')
    except Exception as error:
        report.update(phase='failed',error=type(error).__name__+': '+str(error))
    finally:
        if owned_pid and core.active_model().get('pid')==owned_pid:core.stop_model()
        report['all_models_stopped']=not core.server_ready()
        report['daily_settings_unchanged']=saved==(core.ROOT/'settings.json').read_bytes()
        save();print(json.dumps(report,ensure_ascii=False),flush=True)
    assert report['ok'] and report['all_models_stopped'] and report['daily_settings_unchanged']

if __name__=='__main__':main()
