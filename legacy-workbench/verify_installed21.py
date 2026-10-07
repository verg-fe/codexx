"""Short deployed checks; generation caps belong only to verification requests."""
import base64
import io
import json
import tomllib
from PIL import Image
import core
from verify_hip_runtime import health,response,text

def main():
    saved=core.load_settings();instructions=(core.ROOT/'instructions.md').read_bytes()
    destination=core.ROOT/'verification-installed22.json';report={'ok':False,'checks':{},'short_requests_only':True}
    def check(name,passed):
        report['checks'][name]=bool(passed)
        destination.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        assert passed,name
        print(name,flush=True)
    check('adapter_version',health()['adapter_version']==core.ADAPTER_VERSION)
    check('75k_work_62k_compaction',core.engine_limits(saved)==(76800,63488) and saved['history_mode']=='memory')
    config=tomllib.loads((core.ROOT/'codex-home/config.toml').read_text(encoding='utf-8'))
    check('native_config',config['model_context_window']==76800 and config['model_auto_compact_token_limit']==63488
        and config['approval_policy']=='never')
    check('installed_history_server',config['mcp_servers']['local_history']['command']==str(core.ROOT/'app/MyCodex-history22/MyCodex.exe'))
    live=core.active_model();report['active_model']=live
    check('gpu_weights_and_gpu_kv',live['gpu_layers']=='all' and not live['cpu_offload'] and live['kv_cache_location']=='gpu')
    check('unlimited_reasoning',live['reasoning_budget']==-1)
    result,elapsed=response({'instructions':'只输出计算结果。','input':'17乘19等于多少？'})
    report['text_seconds']=elapsed;check('text','323' in text(result))
    result,elapsed=response({'instructions':'调用 history_checkpoint 工具，不传 state，thread_id 为 11111111-1111-4111-8111-111111111111。',
        'input':'验证工具名。','tools':[{'type':'namespace','name':'mcp__local_history','description':'Local archive tools.',
        'tools':[{'type':'function','name':'history_checkpoint','parameters':{'type':'object',
            'properties':{'thread_id':{'type':'string'}},'required':['thread_id'],'additionalProperties':False}}]}]})
    call=next(i for i in result['output'] if i.get('type')=='function_call')
    report['namespace_function_seconds']=elapsed
    check('real_model_namespace_restored',call['name']=='history_checkpoint' and call.get('namespace')=='mcp__local_history')
    data=io.BytesIO();Image.new('RGB',(96,96),(255,0,0)).save(data,format='WEBP',lossless=True)
    result,elapsed=response({'instructions':'只用一个中文颜色词回答。','input':[{'role':'user','content':[
        {'type':'input_text','text':'图片主要是什么颜色？'},
        {'type':'input_image','image_url':'data:image/webp;base64,'+base64.b64encode(data.getvalue()).decode()}]}]})
    report['image_seconds']=elapsed;check('webp_image','红' in text(result))
    check('policy_unchanged',saved==core.load_settings() and instructions==(core.ROOT/'instructions.md').read_bytes())
    check('model_idle',all(not s.get('is_processing') for s in core.api('/slots')))
    report['ok']=True;destination.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')

if __name__=='__main__':main()
