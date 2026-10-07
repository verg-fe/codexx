"""Short live checks only. No long-context fill or maximum-capacity benchmark."""
import copy
import json
from pathlib import Path
import queue
import time
import urllib.request

import core
import gateway
from conversations import ConversationStore


def proxy_request(body):
    request=urllib.request.Request('http://127.0.0.1:8081/v1/responses',
        data=json.dumps(body).encode(),headers={
            'Content-Type':'application/json','Authorization':'Bearer '+core.load_settings()['api_key']})
    with urllib.request.urlopen(request,timeout=120) as response:
        return json.load(response)


def main():
    report={'ok':False,'short_requests_only':True,'checks':{},'phase':'starting'}
    output=core.ROOT/'verification-dynamic-context.json'
    def save(phase):
        report['phase']=phase
        output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(phase,flush=True)
    rpc=None
    try:
        core.start_model(wait=True)
        live=core.active_model()
        assert live['context']==109568 and live['context_limit']==256000
        assert live['reasoning_budget']==-1 and live['kv_cache_location']=='gpu' and live['gpu_layers']=='all'
        props=core.api('/props')['default_generation_settings']
        assert props['params']['n_predict']==-1
        report['checks']['256k_ceiling_107k_gpu_service_unrestricted']=True
        body={'model':core.MODEL,'instructions':'回答计算结果，只输出数字。',
            'input':[{'role':'user','content':'17乘19等于多少？'}],
            'reasoning':{'effort':'none'},'max_output_tokens':32,'temperature':0,'stream':False}
        expected=gateway.count_prompt_tokens(gateway.normalize(copy.deepcopy(body)),'/v1/responses')
        response=proxy_request(body)
        text=''.join(block.get('text','') for item in response.get('output',[])
                    for block in item.get('content',[]) if item.get('type')=='message')
        # This explicit 32-token test can end during Jack's reasoning/protocol.
        # Validate accounting here; the uncapped coding turn validates real output.
        assert response.get('status')=='completed',response.get('status')
        actual=response['usage']['input_tokens']
        assert expected==actual,(expected,actual)
        report['checks']['actual_template_token_count_matches_inference']=True
        report['prompt_tokens']={'counted':expected,'actual':actual}
        first_pid=core.active_model()['pid']
        proxy_request(body)
        assert core.active_model()['pid']==first_pid
        report['checks']['repeated_requests_keep_gpu_model_and_cache']=True
        save('checking_original_failed_webp_attachment')
        failed=next((core.ROOT/'codex-home/sessions').rglob('*01a0fe00-fb92-7b23-bd08-d463427b24ce.jsonl'))
        image_url=None
        for line in failed.open(encoding='utf-8'):
            entry=json.loads(line)
            if entry.get('type')=='response_item':
                content=entry.get('payload',{}).get('content',[])
                if isinstance(content,list):
                    for block in content:
                        if block.get('type')=='input_image':image_url=block['image_url']
        assert image_url and image_url.startswith('data:image/webp;base64,')
        image_body={'model':core.MODEL,'input':[{'role':'user','content':[
            {'type':'input_text','text':'只回复：收到图片。'}, {'type':'input_image','image_url':image_url}]}],
            'reasoning':{'effort':'none'},'max_output_tokens':32,'temperature':0,'stream':False}
        image_response=proxy_request(image_body)
        assert image_response.get('status')=='completed',image_response.get('error')
        image_route=json.loads((core.ROOT/'request-routing.json').read_text(encoding='utf-8'))
        assert image_route['media_converted_to_png']==1
        report['checks']['original_failed_webp_image_is_accepted_by_live_model']=True
        report['media_fix_verified_model']=core.MODEL
        save('checking_ram_branch_with_short_math_only')
        # Only simulate the policy input count; do not send a 100K/256K prompt.
        core.start_model(wait=True,prompt_tokens=100000)
        live=core.active_model()
        assert live['context']==256000 and live['kv_cache_location']=='ram' and live['gpu_layers']=='all'
        response=core.api('/completion',{'prompt':'<|im_start|>user\n17乘19等于多少？只给数字。<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n',
            'n_predict':32,'temperature':0,'cache_prompt':False},timeout=120)
        assert '323' in response.get('content','')
        report['checks']['ram_branch_real_all_gpu_weights_short_reply']=True
        report['ram_branch_input_count_was_simulated']=True
        core.start_model(wait=True,prompt_tokens=0)
        assert core.active_model()['context']==109568 and core.active_model()['kv_cache_location']=='gpu'
        report['checks']['short_input_returns_to_gpu']=True
        save('native_coding_turn_without_injected_output_or_reasoning_limits')
        events=queue.Queue()
        rpc=core.RpcClient(events.put)
        project=core.ROOT/'verification-project/dynamic-unrestricted-check'
        project.mkdir(parents=True,exist_ok=True)
        thread=rpc.request('thread/start',{'cwd':str(project),'model':core.MODEL,'modelProvider':'qwen_local',
            'approvalPolicy':'never','sandbox':'danger-full-access','config':{
                'model_context_window':256000,'model_auto_compact_token_limit':223232}})['thread']['id']
        turn_id=rpc.request('turn/start',{'threadId':thread,'model':core.MODEL,'effort':'medium',
            'input':[{'type':'text','text':'请在当前目录创建 dynamic-check.txt，内容只有一行 DYNAMIC_GPU_CONTEXT_OK，然后简短告知完成。'}]})['turn']['id']
        started=time.monotonic()
        visible=[]
        approvals=0
        tools=[]
        while time.monotonic()-started<300:
            try:event=events.get(timeout=.25)
            except queue.Empty:continue
            method=event.get('method')
            params=event.get('params',{})
            if method and 'id' in event:
                approvals+=1
                raise RuntimeError('Unexpected native permission request')
            if method=='item/agentMessage/delta':
                visible.append(params.get('delta',''))
            if method=='item/completed':
                item=params.get('item',{})
                if item.get('type')=='agentMessage' and not visible:
                    visible.append(item.get('text',''))
                if item.get('type') in ('commandExecution','fileChange'):
                    tools.append(item['type'])
            if method=='turn/completed':
                assert not params['turn'].get('error'),params['turn'].get('error')
                break
        else:
            rpc.request('turn/interrupt',{'threadId':thread,'turnId':turn_id})
            raise TimeoutError('Short native coding check exceeded five minutes')
        artifact=project/'dynamic-check.txt'
        assert artifact.exists() and artifact.read_text(encoding='utf-8-sig').strip()=='DYNAMIC_GPU_CONTEXT_OK'
        assert visible and tools
        routing=json.loads((core.ROOT/'request-routing.json').read_text(encoding='utf-8'))
        assert routing['output_reserve']==32768 and routing['reasoning_budget']==-1
        assert routing['runtime_context']==109568 and routing['context_limit']==256000
        report['checks']['native_coding_tools_visible_answer_unrestricted_reasoning']=True
        report['native']={'seconds':round(time.monotonic()-started,2),'thread_id':thread,
            'tool_events':tools,'approval_requests':approvals,'routing':routing,'artifact':str(artifact)}
        save('ui_state_check')
        from app import App
        app=App(smoke=True)
        app.withdraw()
        try:
            app.context_slider.set(256000);app.preview_context(256000)
            assert app.pending_context==256000
            assert '实际输入' in app.cache_hint.cget('text')
            assert '思考无额外' in app.context_info.cget('text')
            app.refresh_status()
            assert '服务窗口 109,568' in app.model_info.cget('text')
            assert '对话上限 256,000' in app.model_info.cget('text')
            # Exercise the actual UI action and native archive API on our test
            # thread, using an isolated local index, never the user's chats.
            store=ConversationStore(core.ROOT/'verification-project/delete-ui-store')
            session={'id':thread,'title':'删除功能验证','project':str(project)}
            store.write(store.index,[session])
            store.path_for(thread).write_text('保存的测试对话',encoding='utf-8')
            app.session_store=store
            app.load_sessions=store.sessions
            app.sessions=[session]
            app.rpc=rpc
            app.thread_id=thread
            app.render_sessions()
            def finish_action():
                deadline=time.monotonic()+15
                while app.session_action_pending and time.monotonic()<deadline:
                    try:event=app.events.get(timeout=.1)
                    except queue.Empty:continue
                    app.handle_event(event)
                assert not app.session_action_pending
                assert 'session_action_failed' not in app.chat.get('1.0','end')
            app.delete_session(session);finish_action()
            assert store.sessions()==[] and app.thread_id is None
            assert app.undo_delete_button.cget('state')=='normal'
            app.undo_delete_session();finish_action()
            assert store.sessions()==[session] and store.deleted_sessions()==[]
            assert store.path_for(thread).read_text(encoding='utf-8')=='保存的测试对话'
            restored=rpc.request('thread/resume',{'threadId':thread,'cwd':str(project),'excludeTurns':True})
            assert restored['thread']['id']==thread
            report['checks']['desktop_delete_undo_and_native_archive_restore']=True
        finally:
            app.rpc=None
            app.destroy()
        rpc.close();rpc=None
        report['checks']['desktop_displays_ceiling_runtime_and_unrestricted_thinking']=True
        report['ok']=True
        save('complete')
    except Exception as error:
        report['error']=str(error)
        save('failed')
        raise
    finally:
        if rpc:rpc.close()


if __name__=='__main__':
    main()
