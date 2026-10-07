"""Test real Codex compaction/retrieval against a deterministic local API fixture.

The user's model is never called. This verifies history and tool plumbing, not
the local model's summary quality.
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import queue
import sys
import tempfile
import threading
import time
from unittest.mock import patch
import core
from history_memory import HistoryMemory, memory_instructions
from gateway import normalize, tool_response_routes, adapt_event, retain_execution_state

def main(exercise_failure=False,frozen=None,report_path=None):
    original=core.ROOT;requests=[];identity={}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            original_body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            routes,custom_names=tool_response_routes(original_body.get('tools',[]))
            body=normalize(original_body);retain_execution_state(body,HistoryMemory(identity['root']));requests.append(body)
            index=len(requests)
            def history_item(name,args):
                tool=next(t for t in body['tools'] if t.get('name','').endswith(name))
                return {'type':'function_call','id':'fc_'+str(index),'call_id':'call_'+str(index),'name':tool['name'],
                        'arguments':json.dumps(args),'status':'completed'}
            if exercise_failure and index==2:
                item={'type':'function_call','id':'fc_failure','call_id':'call_failure','name':'exec_command',
                    'arguments':json.dumps({'cmd':'C:\\Python314\\python.exe -c "raise RuntimeError(\'EXECUTION_FAILURE_7391\')"'}),
                    'status':'completed'}
            elif exercise_failure and index==4:
                item=history_item('history_checkpoint',{'thread_id':identity['thread_id']})
            elif exercise_failure and index==5:
                failure=HistoryMemory(identity['root']).execution_snapshot(identity['thread_id'])['failures'][-1]
                item=history_item('history_read',{'thread_id':identity['thread_id'],'record_id':failure['record_id']})
            elif not exercise_failure and index==2:
                flattened=[]
                for candidate in body['tools']:
                    if candidate.get('type')=='namespace':
                        flattened.extend({**t,'name':candidate['name']+'__'+t['name']} for t in candidate.get('tools',[]))
                    else:flattened.append(candidate)
                matches=[t for t in flattened if t.get('name','').endswith('history_search')]
                if not matches:raise AssertionError('Missing history tool: '+json.dumps([{k:t.get(k) for k in ('name','type','namespace')} for t in body['tools']]))
                tool=matches[0]
                item={'type':'function_call','id':'fc_fixture','call_id':'call_fixture','name':tool['name'],
                    'arguments':json.dumps({'thread_id':identity['thread_id'],'query':'ARCHIVE_PRECOMPACT_9853'}),
                    'status':'completed'}
            elif (not exercise_failure and index==3) or (exercise_failure and index==6):
                item={'type':'function_call','id':'fc_unicode','call_id':'call_unicode','name':'exec_command',
                    'arguments':json.dumps({'cmd':'C:\\Python314\\python.exe -c "print(\'\\u9e48\\u9e55\')"'}),
                    'status':'completed'}
            else:
                text='CHECKPOINT: preserve the objective and query the archived original when exact details are needed.' if index==1 or (exercise_failure and index==3) else 'Archive retrieval completed.'
                item={'type':'message','id':'msg_'+str(index),'role':'assistant','status':'completed',
                    'content':[{'type':'output_text','text':text,'annotations':[]}]}
            response={'id':'resp_'+str(index),'object':'response','model':core.MODEL,'status':'in_progress','output':[]}
            events=[{'type':'response.created','response':response},
                {'type':'response.output_item.added','output_index':0,'item':{**item,'status':'in_progress'}}]
            if item['type']=='message':
                events.append({'type':'response.output_text.delta','output_index':0,'item_id':item['id'],
                    'content_index':0,'delta':item['content'][0]['text']})
            usage_input=65000 if exercise_failure and index==2 else 1000
            events.extend([{'type':'response.output_item.done','output_index':0,'item':item},
                {'type':'response.completed','response':{**response,'status':'completed','output':[item],
                    'usage':{'input_tokens':usage_input,'output_tokens':50,'total_tokens':usage_input+50}}}])
            ids=set()
            events=[converted for event in events for converted in adapt_event(event,custom_names,ids,routes)]
            payload=''.join('data: '+json.dumps(e)+'\n\n' for e in events).encode()
            self.send_response(200);self.send_header('Content-Type','text/event-stream')
            self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
    base=(original/'verification-project').resolve();base.mkdir(exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(prefix='history-compact-',dir=base) as directory:
            root=Path(directory).resolve();assert root.is_relative_to(base)
            identity['root']=root
            (root/'engine').mkdir();os.link(original/'engine/codex.exe',root/'engine/codex.exe')
            settings={'model':core.MODEL,'context':256000,'model_contexts':{core.MODEL:256000},
                'project':str(root),'api_key':'__REDACTED__','history_mode':'memory','work_context':76800}
            events=queue.Queue()
            with patch.object(core,'ROOT',root),patch.object(core.Path,'home',return_value=root/'no-home'):
                if frozen:
                    with patch.object(core.sys,'frozen',True,create=True),patch.object(core.sys,'executable',str(frozen)):
                        core.prepare(settings)
                else:core.prepare(settings)
                path=root/'codex-home/config.toml'
                path.write_text(path.read_text().replace('127.0.0.1:8081',f'127.0.0.1:{server.server_port}'))
                rpc=core.RpcClient(events.put)
                try:
                    thread=rpc.request('thread/start',{'cwd':str(root),'model':core.MODEL,
                        'modelProvider':'qwen_local','approvalPolicy':'never','sandbox':'danger-full-access',
                        'config':core.engine_config(settings)})['thread']
                    tid=thread['id'];identity['thread_id']=tid
                    deadline=time.monotonic()+25
                    while True:
                        if 'history_search' in json.dumps(rpc.request('mcpServerStatus/list',{'detail':'full'})):break
                        if time.monotonic()>deadline:raise AssertionError('History MCP tools unavailable')
                        time.sleep(.25)
                    old='ARCHIVE_PRECOMPACT_9853\n'+('Old exact evidence retained outside the working prompt.\n'*5000)
                    rpc.request('thread/inject_items',{'threadId':tid,'items':[{'type':'message','role':'assistant',
                        'content':[{'type':'output_text','text':old}]},{'type':'message','role':'user',
                        'content':[{'type':'input_text','text':'Continue the current task and retain the exact evidence in the archive.'}]}]})
                    memory=HistoryMemory(root);rollout=memory.find_rollout(tid)
                    before=rollout.read_bytes()
                    rpc.request('thread/compact/start',{'threadId':tid})
                    deadline=time.monotonic()+45
                    compact_item_done=False;compact_turn_done=False
                    while True:
                        event=events.get(timeout=max(.1,deadline-time.monotonic()))
                        if event.get('method')=='item/completed' and event.get('params',{}).get('item',{}).get('type')=='contextCompaction':compact_item_done=True
                        if event.get('method')=='turn/completed':compact_turn_done=True
                        if compact_item_done and compact_turn_done:break
                        if event.get('method')=='error':raise AssertionError(str(event))
                        if time.monotonic()>deadline:raise AssertionError('Compaction did not finish')
                    assert rollout.read_bytes().startswith(before),'Compaction rewrote the raw archive'
                    assert memory.search(tid,'ARCHIVE_PRECOMPACT_9853')['results']
                    turn=rpc.request('turn/start',{'threadId':tid,'input':[{'type':'text','text':'Read exact evidence from the original archive.'}],
                        'collaborationMode':{'mode':'default','settings':{'model':core.MODEL,'reasoning_effort':'low',
                            'developer_instructions':memory_instructions(tid)}}})['turn']
                    deadline=time.monotonic()+45
                    while True:
                        event=events.get(timeout=max(.1,deadline-time.monotonic()))
                        if (event.get('method')=='turn/completed' and
                                event.get('params',{}).get('turn',{}).get('id')==turn['id']):break
                        if event.get('method')=='error':raise AssertionError(str(event))
                        if time.monotonic()>deadline:raise AssertionError('Retrieval turn did not finish')
                    if exercise_failure:
                        assert len(requests)==7, len(requests)
                        assert any(i.get('type')=='function_call_output' and 'EXECUTION_FAILURE_7391' in json.dumps(i.get('output'))
                            for i in requests[2].get('input',[])),'Actual command did not fail as intended'
                        compact_rows=[json.loads(l) for l in rollout.read_text(encoding='utf-8').splitlines() if l.strip()]
                        summaries=[r['payload']['message'] for r in compact_rows if r.get('type')=='compacted']
                        assert len(summaries)==2 and 'EXECUTION_FAILURE_7391' not in summaries[-1]
                        assert 'EXECUTION_FAILURE_7391' in requests[3]['instructions'], 'Failure missing after automatic compaction'
                        checkpoint_results=[i for i in requests[4].get('input',[]) if i.get('type')=='function_call_output' and i.get('call_id')=='call_4']
                        assert any('EXECUTION_FAILURE_7391' in json.dumps(i.get('output')) and 'execution' in json.dumps(i.get('output'))
                            for i in checkpoint_results),'Checkpoint did not return independent execution state'
                        read_results=[i for i in requests[5].get('input',[]) if i.get('type')=='function_call_output' and i.get('call_id')=='call_5']
                        assert any('EXECUTION_FAILURE_7391' in json.dumps(i.get('output')) and 'RuntimeError' in json.dumps(i.get('output'))
                            for i in read_results),'Native history_read did not return exact original error'
                        assert '\u9e48\u9e55' in json.dumps(requests[6].get('input'),ensure_ascii=False)
                        report={'ok':True,'real_user_model_requests':0,'frozen_mcp':bool(frozen),'checks':{
                            'native_failed_command_observed':True,'automatic_compaction_omitted_error':True,
                            'error_reinjected_after_compaction':True,'native_checkpoint_returns_failure':True,
                            'native_history_read_returns_exact_error':True,'native_namespace_roundtrip':True,
                            'working_context_75k_compact_62k':core.engine_limits(settings)==(76800,63488)}}
                        Path(report_path or original/'verification-execution-compaction21.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
                        print(json.dumps(report),flush=True)
                        return
                    second=json.dumps(requests[1].get('input'));third=json.dumps(requests[2].get('input'))
                    assert 'CHECKPOINT' in second
                    assert 'Old exact evidence retained' not in second,'Full history leaked back into the working prompt'
                    result_items=[i for i in requests[2].get('input',[]) if i.get('type')=='function_call_output']
                    assert any('ARCHIVE_PRECOMPACT_9853' in json.dumps(i.get('output')) for i in result_items), \
                        'Real MCP tool RESULT did not return archived evidence: '+json.dumps(result_items)
                    assert not any('unsupported call:' in json.dumps(i.get('output')) for i in result_items)
                    assert '\u9e48\u9e55' in json.dumps(requests[3].get('input'),ensure_ascii=False),'Native Python tool output corrupted Chinese'
                    report={'ok':True,'real_user_model_requests':0,'original_archive_bytes':len(before),
                        'working_input_bytes_after_compaction':len(second),'checks':{
                            'native_compaction_preserves_raw_history':True,'working_prompt_replaced_with_summary':True,
                            'agent_tool_result_recalls_exact_archived_evidence':True,'native_namespace_roundtrip':True,
                            'native_python_tool_output_utf8':True,'working_context_75k_compact_62k':core.engine_limits(settings)==(76800,63488)}}
                    Path(report_path or original/'verification-history-compaction.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
                    print(json.dumps(report),flush=True)
                finally:rpc.close()
    finally:server.shutdown();server.server_close();worker.join(timeout=2)

if __name__=='__main__':
    frozen=Path(sys.argv[sys.argv.index('--frozen')+1]).resolve() if '--frozen' in sys.argv else None
    report_path=Path(sys.argv[sys.argv.index('--report')+1]).resolve() if '--report' in sys.argv else None
    main('--execution-failure' in sys.argv,frozen,report_path)
