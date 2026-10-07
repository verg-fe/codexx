"""Actual native Codex compaction/MCP/exec with a deterministic private provider."""
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json,os,sys
from pathlib import Path
import queue,tempfile,threading,time
from unittest.mock import patch
import core
from gateway import normalize,tool_response_routes,adapt_event,attach_task_state
from generation_trace import GenerationTrace
from history_memory import memory_instructions
from task_artifacts import TaskArtifacts


def main(frozen=None):
    original=core.ROOT;requests=[];identity={}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            raw=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            routes,names=tool_response_routes(raw.get('tools',[]));body=normalize(raw)
            attach_task_state(body,identity['root']);requests.append(body);index=len(requests)
            def tool(name,args):
                candidate=next(t for t in body['tools'] if t.get('name','').endswith(name))
                return {'type':'function_call','id':f'fc{index}','call_id':f'call{index}',
                        'name':candidate['name'],'arguments':json.dumps(args),'status':'completed'}
            if index==2:item=tool('draft_list',{'thread_id':identity['thread_id']})
            elif index==3:item=tool('draft_read',{'thread_id':identity['thread_id'],'draft_id':identity['draft_id']})
            elif index==4:
                old=str(identity['old'])
                cmd=f"try {{ Get-Content -LiteralPath '{old}' -Raw -ErrorAction Stop; throw 'LOCK_FAILED' }} catch {{ if ($_.Exception.Message -like '*LOCK_FAILED*') {{ throw }}; Write-Output 'OLD_READ_LOCKED' }}; Set-Content -LiteralPath 'new.svg' -Encoding utf8 -Value '<svg xmlns=\"http://www.w3.org/2000/svg\"/>'; Write-Output ((Get-Location).Path)"
                item={'type':'function_call','id':'fc_exec','call_id':'call_exec','name':'exec_command',
                      'arguments':json.dumps({'cmd':cmd}),'status':'completed'}
            else:
                text='Checkpoint: SVG task still needs implementation. Details omitted.' if index==1 else '本轮文件已创建。'
                item={'type':'message','id':f'msg{index}','role':'assistant','status':'completed',
                      'content':[{'type':'output_text','text':text,'annotations':[]}]}
            response={'id':f'resp{index}','object':'response','model':core.MODEL,'status':'in_progress','output':[]}
            events=[{'type':'response.created','response':response},
                    {'type':'response.output_item.added','output_index':0,'item':{**item,'status':'in_progress'}}]
            if item['type']=='message':events.append({'type':'response.output_text.delta','output_index':0,'item_id':item['id'],'content_index':0,'delta':item['content'][0]['text']})
            events.extend([{'type':'response.output_item.done','output_index':0,'item':item},
                {'type':'response.completed','response':{**response,'status':'completed','output':[item],
                    'usage':{'input_tokens':1000,'output_tokens':30,'total_tokens':1030}}}])
            ids=set();events=[out for event in events for out in adapt_event(event,names,ids,routes)]
            data=''.join('data: '+json.dumps(event)+'\n\n' for event in events).encode()
            self.send_response(200);self.send_header('Content-Type','text/event-stream');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
    lock=None;rpc=None
    try:
        with tempfile.TemporaryDirectory(prefix='draft-native23-',dir=original/'verification-project') as directory:
            root=Path(directory);identity['root']=root
            (root/'engine').mkdir();os.link(original/'engine/codex.exe',root/'engine/codex.exe')
            settings={'model':core.MODEL,'project':str(root),'api_key':'__REDACTED__','context':256000,
                      'model_contexts':{core.MODEL:256000},'history_mode':'memory','work_context':76800}
            events=queue.Queue()
            with patch.object(core,'ROOT',root),patch.object(core.Path,'home',return_value=root/'no-home'):
                if frozen:
                    with patch.object(core.sys,'frozen',True,create=True),patch.object(core.sys,'executable',str(frozen)):
                        core.prepare(settings)
                else:core.prepare(settings)
                config=root/'codex-home/config.toml';config.write_text(config.read_text().replace('127.0.0.1:8081',f'127.0.0.1:{server.server_port}'))
                rpc=core.RpcClient(events.put)
                try:
                    thread=rpc.request('thread/start',{'cwd':str(root),'model':core.MODEL,'modelProvider':'qwen_local',
                        'sandbox':'danger-full-access','approvalPolicy':'never','config':core.engine_config(settings)})['thread']
                    tid=thread['id'];identity['thread_id']=tid
                    old=root/'old.svg';old.write_text('<svg>OLD_TASK_FILE</svg>');identity['old']=old
                    store=TaskArtifacts(root);state,lock=store.begin(tid,root,'画一只鹈鹕 SVG 动画')
                    identity['new']=Path(state['workdir'])/'new.svg'
                    trace=GenerationTrace(root/'logs/generation',{'thread_id':tid,'draft_directory':state['draft_directory']})
                    draft='```python\nORIGINAL_DRAFT_BEFORE_COMPACTION = "PelicanCSS"\n```\n'
                    trace.event({'type':'response.reasoning_text.delta','item_id':'r','delta':draft});trace.finish('complete')
                    identity['draft_id']=store.list(tid)['drafts'][0]['id']
                    until=time.monotonic()+25
                    while 'draft_read' not in json.dumps(rpc.request('mcpServerStatus/list',{'detail':'full'})):
                        if time.monotonic()>until:raise AssertionError('Native MCP drafts unavailable')
                        time.sleep(.1)
                    rpc.request('thread/compact/start',{'threadId':tid})
                    until=time.monotonic()+25
                    compact_item_done=False;compact_turn_done=False
                    while True:
                        e=events.get(timeout=max(.1,until-time.monotonic()))
                        if e.get('method')=='item/completed' and e.get('params',{}).get('item',{}).get('type')=='contextCompaction':compact_item_done=True
                        if e.get('method')=='turn/completed':compact_turn_done=True
                        if compact_item_done and compact_turn_done:break
                        if e.get('method')=='error':raise AssertionError(e)
                        if time.monotonic()>until:raise AssertionError('Native compaction not completed')
                    turn=rpc.request('turn/start',{'threadId':tid,'cwd':state['workdir'],'model':core.MODEL,
                        'input':[{'type':'text','text':'Finish current SVG using its saved draft.'}],
                        'collaborationMode':{'mode':'default','settings':{'model':core.MODEL,'reasoning_effort':'medium','developer_instructions':memory_instructions(tid)}}})['turn']
                    until=time.monotonic()+40
                    while True:
                        e=events.get(timeout=max(.1,until-time.monotonic()))
                        if e.get('method')=='turn/completed' and e.get('params',{}).get('turn',{}).get('id')==turn['id']:
                            assert e['params']['turn']['status']=='completed',e;break
                        if time.monotonic()>until:raise AssertionError('Native draft roundtrip timeout')
                    assert len(requests)==5,len(requests)
                    assert identity['draft_id'] in requests[1]['instructions']
                    assert 'ORIGINAL_DRAFT_BEFORE_COMPACTION' in json.dumps(requests[3]['input'])
                    assert 'OLD_READ_LOCKED' in json.dumps(requests[4]['input'])
                    assert state['workdir'] in json.dumps(requests[4]['input']).replace('\\\\','\\')
                    assert identity['new'].exists()
                    lock.close();lock=None;assert old.read_text()=='<svg>OLD_TASK_FILE</svg>'
                    result={'ok':True,'frozen_mcp':bool(frozen),'real_model_requests':0,'native_requests':len(requests),'checks':{
                        'compaction_omits_draft_but_pointer_reinjected':True,'real_native_mcp_draft_read':True,
                        'real_shell_old_file_read_blocked':True,'real_native_cwd_new_directory':True,
                        'new_artifact_written_old_file_preserved':True,'locks_released':True}}
                    (original/'verification-draft-native28.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
                    print(json.dumps(result),flush=True)
                finally:
                    if lock:lock.close();lock=None
                    rpc.close();rpc=None
    finally:
        if rpc:rpc.close()
        if lock:lock.close()
        server.shutdown();server.server_close();worker.join(timeout=2)

if __name__=='__main__':
    frozen=Path(sys.argv[sys.argv.index('--frozen')+1]).resolve() if '--frozen' in sys.argv else None
    main(frozen)
