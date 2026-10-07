"""Bounded real model checks after old turns end; normal generation stays unlimited."""
import base64
from http.server import ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import queue
import tempfile
import threading
import time
from unittest.mock import patch

from PIL import Image
import core
import gateway


def complete(messages,**extra):
    return core.api('/v1/chat/completions',{'model':core.MODEL,'messages':messages,'temperature':0,
        'max_tokens':256,'chat_template_kwargs':{'enable_thinking':False},**extra},timeout=90)


def native_file_check(original):
    events=queue.Queue();rpc=None;server=None;worker=None;turn_id=None;thread_id=None
    with tempfile.TemporaryDirectory(prefix='profiles26-file-',dir=original/'verification-project') as folder:
        root=Path(folder);(root/'engine').mkdir();os.link(original/'engine/codex.exe',root/'engine/codex.exe')
        settings={**core.load_settings(),'project':str(root)}
        def route(body,route,settings,name,media):
            # Test-only overrides never reach the saved daily configuration.
            body['chat_template_kwargs']={'enable_thinking':False}
            body['max_output_tokens']=512;body['temperature']=0
            body['reasoning']={'effort':'none'}
            return {'model':name,'runtime_context':core.GPU_CONTEXT_LIMIT,'profiles26_test_only':True}
        try:
            with patch.object(core,'ROOT',root),patch.object(core.Path,'home',return_value=root/'no-global-home'),\
                 patch.object(gateway,'ROOT',root),patch.object(gateway,'route_inference',side_effect=route):
                core.prepare(settings)
                server=ThreadingHTTPServer(('127.0.0.1',0),gateway.Handler)
                server.daemon_threads=True
                worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
                config=root/'codex-home/config.toml'
                config.write_text(config.read_text(encoding='utf-8').replace('127.0.0.1:8081',f'127.0.0.1:{server.server_port}'),encoding='utf-8')
                rpc=core.RpcClient(events.put)
                thread_id=rpc.request('thread/start',{'cwd':str(root),'model':core.MODEL,'modelProvider':'qwen_local',
                    'sandbox':'danger-full-access','approvalPolicy':'never','config':core.engine_config(settings)})['thread']['id']
                prompt='请在当前目录创建 probe.txt，UTF-8 内容精确为 profiles26 文件工具正常（不要加换行）。然后用 exec_command 运行 Python 读取并 assert 内容正确，打印 PROFILES26_FILE_VERIFIED。必须实际执行，最后简短说明文件位置。'
                turn_id=rpc.request('turn/start',{'threadId':thread_id,'input':[{'type':'text','text':prompt}]})['turn']['id']
                deadline=time.monotonic()+100;outputs=[];answers=[];finished=None;output_deltas={}
                while time.monotonic()<deadline:
                    event=events.get(timeout=max(.1,deadline-time.monotonic()))
                    method=event.get('method');params=event.get('params',{})
                    if method=='item/commandExecution/outputDelta':
                        item_id=params.get('itemId')
                        output_deltas[item_id]=output_deltas.get(item_id,'')+params.get('delta','')
                    if 'id' in event and method in ('item/commandExecution/requestApproval','item/fileChange/requestApproval'):
                        rpc.send({'id':event['id'],'result':{'decision':'accept'}})
                    if method=='item/completed':
                        item=params.get('item',{})
                        if item.get('type')=='commandExecution':
                            item['observedOutput']=output_deltas.get(item.get('id'),'');outputs.append(item)
                        if item.get('type')=='agentMessage':answers.append(item.get('text',''))
                    if method=='turn/completed' and params.get('turn',{}).get('id')==turn_id:
                        finished=params['turn'];break
                assert finished and finished.get('status')=='completed',finished
                assert (root/'probe.txt').read_bytes()=='profiles26 文件工具正常'.encode('utf-8')
                assert any(item.get('exitCode')==0 and 'PROFILES26_FILE_VERIFIED' in
                    ((item.get('aggregatedOutput') or '')+item['observedOutput']) for item in outputs),outputs
                assert any(text.strip() for text in answers)
                return {'ok':True,'real_native_file_written':True,'real_native_validation_command_passed':True,
                        'native_final_body':True,'test_only_cap':512,'daily_settings_changed':False}
        finally:
            if rpc:
                if turn_id and not locals().get('finished'):
                    try:rpc.request('turn/interrupt',{'threadId':thread_id,'turnId':turn_id})
                    except Exception:pass
                rpc.close()
            if server:server.shutdown();server.server_close()
            if worker:worker.join(timeout=2)


def main():
    original=core.ROOT;saved=(original/'settings.json').read_bytes()
    report={'ok':False,'phase':'testing','scope':'fresh short requests and a private native file task; not a long-task intelligence comparison',
            'test_only_generation_limits':True,'checks':{}}
    try:
        live=core.active_model()
        assert live.get('chat_template_policy')=='jack-profile-v26'
        assert not any(slot.get('is_processing') for slot in core.api('/slots'))
        props=core.api('/props')
        served=props.get('chat_template','')
        assert served==Path(live['chat_template_file']).read_text(encoding='utf-8') and '<workspace_state>' not in served
        rendered=core.api('/apply-template',{'messages':[{'role':'system','content':'Private probe.'},{'role':'user','content':'Hello'}]})['prompt']
        assert '<Prime_Directive profile=\"obedient\">' in rendered and '<workspace_state>' not in rendered
        report['checks']['server_template_override']=True
        value=complete([{'role':'user','content':'17 * 19 = ? Return only the integer.'}],
            chat_template_kwargs={'enable_thinking':True,'reasoning_effort':'low'})
        message=value['choices'][0]['message']
        assert '323' in (message.get('content') or '')
        assert (message.get('reasoning_content') or '').strip()
        report['checks']['native_thinking_and_text']=True
        report['fresh_answer_has_xml']=any(tag in json.dumps(message) for tag in ('<workspace_state>','<pitfall_check>','<grounded_source>'))
        report['short_request_timings']=value.get('timings')
        tool=complete([{'role':'user','content':'Call ping with message profiles26-ready.'}],tools=[{'type':'function','function':
            {'name':'ping','parameters':{'type':'object','properties':{'message':{'type':'string'}},'required':['message']}}}],
            tool_choice={'type':'function','function':{'name':'ping'}})
        call=tool['choices'][0]['message']['tool_calls'][0]['function']
        assert call['name']=='ping' and json.loads(call['arguments'])['message']=='profiles26-ready'
        report['checks']['parsed_tool_call']=True
        buf=io.BytesIO();Image.new('RGB',(96,96),(255,0,0)).save(buf,format='PNG')
        url='data:image/png;base64,'+base64.b64encode(buf.getvalue()).decode()
        image=complete([{'role':'user','content':[{'type':'text','text':'Main color? One word.'},{'type':'image_url','image_url':{'url':url}}]}])
        answer=image['choices'][0]['message'].get('content') or ''
        assert 'red' in answer.lower() or '红' in answer
        report['checks']['real_image']=True
        report['native_file']=native_file_check(original)
        report['checks']['native_tools_and_file']=report['native_file']['ok']
        report['settings_unchanged']=saved==(original/'settings.json').read_bytes()
        assert report['settings_unchanged']
        report.update(ok=True,phase='complete')
    except Exception as error:
        report.update(phase='failed',error=str(error))
        raise
    finally:
        (original/'verification-profiles26-runtime.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'ok':report['ok'],'checks':report['checks'],'fresh_answer_has_xml':report['fresh_answer_has_xml']}),flush=True)


if __name__=='__main__':main()
