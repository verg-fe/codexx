"""Short real adapter probes; leave the user's sampling and thinking unchanged."""
import base64
import io
import json
from pathlib import Path
import queue
import tempfile
import os
import threading
import time
import urllib.request
from http.server import ThreadingHTTPServer
from unittest.mock import patch
from PIL import Image
import core
import gateway

def response(body):
    request=urllib.request.Request('http://127.0.0.1:8081/v1/responses',
        data=json.dumps(body,ensure_ascii=False).encode(),headers={
            'Authorization':'Bearer '+core.load_settings()['api_key'],'Content-Type':'application/json'})
    with urllib.request.urlopen(request,timeout=90) as stream:
        if body.get('stream'):
            events=[]
            for line in stream:
                if line.startswith(b'data: ') and line.strip()!=b'data: [DONE]':events.append(json.loads(line[6:]))
            return events
        return json.load(stream)

def native_file_check():
    original=core.ROOT;events=queue.Queue();rpc=None;server=None;worker=None;finished=None;turn=None;thread=None
    with tempfile.TemporaryDirectory(prefix='native32-',dir=original/'verification-project') as directory:
        root=Path(directory);(root/'engine').mkdir();os.link(original/'engine/codex.exe',root/'engine/codex.exe')
        settings={**core.load_settings(),'project':str(root)}
        def route(body,route,settings,name,media):
            body['chat_template_kwargs']={'enable_thinking':False}
            body['max_output_tokens']=2048;body['temperature']=0;body['reasoning']={'effort':'none'}
            return {'model':name,'runtime_context':core.GPU_CONTEXT_LIMIT,'test_only':True}
        try:
            with patch.object(core,'ROOT',root),patch.object(core.Path,'home',return_value=root/'no-global-home'),\
                 patch.object(gateway,'ROOT',root),patch.object(gateway,'route_inference',side_effect=route):
                core.prepare(settings)
                server=ThreadingHTTPServer(('127.0.0.1',0),gateway.Handler);server.daemon_threads=True
                worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
                config=root/'codex-home/config.toml'
                config.write_text(config.read_text(encoding='utf-8').replace('127.0.0.1:8081',f'127.0.0.1:{server.server_port}'),encoding='utf-8')
                rpc=core.RpcClient(events.put)
                thread=rpc.request('thread/start',{'cwd':str(root),'model':core.MODEL,'modelProvider':'qwen_local',
                    'sandbox':'danger-full-access','approvalPolicy':'never','config':core.engine_config(settings)})['thread']['id']
                turn=rpc.request('turn/start',{'threadId':thread,'input':[{'type':'text','text':
                    '请只用一次 exec_command 工具在当前目录创建 probe.txt，UTF-8 内容为 native32 文件正常（不加换行），在同一条命令里读回文件并 assert 内容正确，最后打印 NATIVE32_FILE_VERIFIED。请实际执行，完成后简短回答。'}]})['turn']['id']
                until=time.monotonic()+130;outputs=[]
                while time.monotonic()<until:
                    event=events.get(timeout=max(.1,until-time.monotonic()));method=event.get('method');params=event.get('params',{})
                    if 'id' in event and method in ('item/commandExecution/requestApproval','item/fileChange/requestApproval'):
                        rpc.send({'id':event['id'],'result':{'decision':'accept'}})
                    if method=='item/completed' and params.get('item',{}).get('type')=='commandExecution':
                        item=params['item'];outputs.append(item)
                        if item.get('exitCode')==0 and 'NATIVE32_FILE_VERIFIED' in item.get('aggregatedOutput',''):
                            # The probe ends at the verified tool boundary. It is
                            # not an evaluation of this model's final answer.
                            assert (root/'probe.txt').read_bytes()=='native32 文件正常'.encode('utf-8')
                            rpc.request('turn/interrupt',{'threadId':thread,'turnId':turn})
                            while time.monotonic()<until:
                                last=events.get(timeout=max(.1,until-time.monotonic()))
                                if last.get('method')=='turn/completed' and last.get('params',{}).get('turn',{}).get('id')==turn:
                                    finished=last['params']['turn'];break
                            assert finished and finished.get('status') in ('interrupted','completed'), 'Private probe did not terminate'
                            return {'real_file_written':True,'validation_command_passed':True,
                                    'native_terminal_observed':True,'bounded_at_verified_tool_boundary':True}
                    if method=='turn/completed' and params.get('turn',{}).get('id')==turn:
                        finished=params['turn'];break
                assert finished and finished.get('status')=='completed','Private native task did not complete'
                assert (root/'probe.txt').read_bytes()=='native32 文件正常'.encode('utf-8'),'Native file content'
                assert any(x.get('exitCode')==0 and 'NATIVE32_FILE_VERIFIED' in x.get('aggregatedOutput','') for x in outputs),'Native validation command'
                return {'real_file_written':True,'validation_command_passed':True,'native_terminal_observed':True,
                        'bounded_at_verified_tool_boundary':True}
        finally:
            if rpc:
                if turn and not finished:
                    try:rpc.request('turn/interrupt',{'threadId':thread,'turnId':turn})
                    except Exception:pass
                rpc.close()
            if server:server.shutdown();server.server_close()
            if worker:worker.join(timeout=2)

def main():
    root=core.ROOT;saved=(root/'settings.json').read_bytes();report={'ok':False,'checks':{},
        'scope':'Short real Responses stream and private native file task, not a long-context speed guarantee'}
    try:
        assert not any(s.get('is_processing') for s in core.api('/slots'))
        base={'model':core.MODEL,'instructions':'Private adapter32 verification. Keep the requested actions precise.',
            'temperature':0,'max_output_tokens':64,'chat_template_kwargs':{'enable_thinking':False},'stream':True}
        events=response({**base,'input':'用中文回答：17乘19是多少？'})
        assert any(e['type']=='response.completed' for e in events),'Responses terminal event'
        assert any(e['type'] in ('response.output_text.delta','response.reasoning_text.delta') for e in events),'Responses generated text'
        report['checks']['real_responses_stream']=True
        report['checks']['unlimited_daily_thinking']=core.active_model().get('reasoning_budget')==-1
        report['checks']['gpu_weights_and_kv']=core.active_model().get('kv_cache_location')=='gpu' and core.active_model().get('gpu_layers') in ('all',999)
        report['native_file']=native_file_check();report['checks']['real_native_tool_and_file']=all(report['native_file'].values())
        report['checks']['daily_settings_unchanged']=(root/'settings.json').read_bytes()==saved
        report['ok']=all(report['checks'].values());assert report['ok'],report['checks']
    except Exception as error:
        report['error']=(type(error).__name__+': '+str(error)).replace(core.load_settings()['api_key'],'[redacted]')
        raise
    finally:
        (root/'verification-runtime32.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False),flush=True)

if __name__=='__main__':main()
