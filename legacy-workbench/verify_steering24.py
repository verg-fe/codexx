"""Desktop steering checks plus a real native app-server, using a private deterministic provider."""
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json,os,queue,subprocess,sys,tempfile,threading,time,unittest
from pathlib import Path
from unittest.mock import patch
import app as desktop
import core
from gateway import adapt_event,normalize,tool_response_routes

class DesktopSteering(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        settings={**core.load_settings(),'project':str(self.root)}
        self.patches=[patch.object(desktop,'ROOT',self.root),patch.object(desktop,'prepare',return_value=settings)]
        for p in self.patches:p.start()
        self.ui=desktop.App(smoke=True);self.ui.withdraw();self.ui.update()
        self.ui.thread_id='11111111-1111-4111-8111-111111111111'
        self.ui.turn_id='turn-original';self.ui.busy=True
        self.ui.background=lambda fn:fn()

    def tearDown(self):
        for timer in self.ui.tk.call('after','info'):self.ui.tk.call('after','cancel',timer)
        self.ui.artifact_locks.close();self.ui.destroy()
        for p in reversed(self.patches):p.stop()
        self.tmp.cleanup()

    def test_current_output_and_guidance_both_survive_later_streaming(self):
        self.ui.handle_event({'method':'item/agentMessage/delta','params':{'itemId':'a','delta':'BEFORE'}})
        old_start=self.ui.turn_started_at;old_buffers=dict(self.ui.message_buffers)
        calls=[]
        class Rpc:
            def request(self,method,params):calls.append((method,params));return {'turnId':'turn-original'}
        self.ui.rpc=Rpc();self.ui.input.insert('1.0','GUIDE_KEEP_ON_SCREEN')
        self.ui.send_prompt()
        self.ui.handle_event(self.ui.events.get_nowait())
        self.ui.handle_event({'method':'item/agentMessage/delta','params':{'itemId':'a','delta':'_AFTER'}})
        shown=self.ui.chat.get('1.0','end')
        self.assertIn('BEFORE_AFTER',shown);self.assertIn('GUIDE_KEEP_ON_SCREEN',shown)
        self.assertIn('引导已提交',shown);self.assertTrue(self.ui.busy)
        self.assertEqual(self.ui.turn_id,'turn-original');self.assertEqual(self.ui.turn_started_at,old_start)
        self.assertEqual(calls[0][0],'turn/steer');self.assertEqual(len(calls),1)
        self.assertEqual(calls[0][1]['expectedTurnId'],'turn-original')
        self.assertEqual(self.ui.send_button.cget('state'),'normal')
        self.assertEqual(self.ui.send_button.cget('text'),'引导  ↗')

    def test_rejected_steer_preserves_new_text_and_images_and_active_turn(self):
        class Rpc:
            def request(self,*args):raise RuntimeError('ActiveTurnNotSteerable')
        self.ui.rpc=Rpc();self.ui.attachments=['old-reference.png']
        self.ui.input.insert('1.0','ORIGINAL_GUIDE');self.ui.send_prompt()
        self.ui.input.insert('1.0','NEWLY_TYPED');self.ui.attachments=['new-reference.png']
        self.ui.handle_event(self.ui.events.get_nowait())
        self.assertIn('ORIGINAL_GUIDE',self.ui.input.get('1.0','end'))
        self.assertIn('NEWLY_TYPED',self.ui.input.get('1.0','end'))
        self.assertEqual(self.ui.attachments,['old-reference.png','new-reference.png'])
        self.assertTrue(self.ui.busy);self.assertEqual(self.ui.turn_id,'turn-original')
        self.assertFalse(self.ui.steer_pending)

    def test_pending_ack_disables_duplicate_submit_and_keeps_next_chat_blocked(self):
        self.ui.steer_pending=True;self.ui.busy=False;self.ui.sync_send_button()
        self.assertEqual(self.ui.send_button.cget('state'),'disabled')
        self.ui.new_chat();self.assertIsNotNone(self.ui.thread_id)

    def test_steering_keeps_task_id_and_old_locks_but_allows_selected_reference(self):
        from task_artifacts import TaskArtifacts
        old=self.root/'old.svg';old.write_text('original old')
        image=self.root/'reference.png';image.write_bytes(b'explicit user image')
        store=TaskArtifacts(self.root)
        state,self.ui.artifact_locks=store.begin(self.ui.thread_id,self.root,'创建 SVG 动画')
        self.ui.artifact_task=state
        class Rpc:
            def request(self,method,params):return {'turnId':'turn-original'}
        self.ui.rpc=Rpc();self.ui.attachments=[str(image)];self.ui.input.insert('1.0','按这张图继续')
        self.ui.send_prompt();self.ui.handle_event(self.ui.events.get_nowait())
        self.assertEqual(store.current(self.ui.thread_id)['task_id'],state['task_id'])
        with self.assertRaises(PermissionError):old.read_text()
        self.assertEqual(image.read_bytes(),b'explicit user image')


def native_check(final_only=False):
    original=core.ROOT;requests=[];notifications=[];first_open=threading.Event();release=threading.Event()
    stream_after_steer=threading.Event();stream_closed_early=threading.Event()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            raw=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            routes,names=tool_response_routes(raw.get('tools',[]));body=normalize(raw);requests.append(body);index=len(requests)
            def message(text):return {'type':'message','id':f'msg{index}','role':'assistant','status':'completed',
                'content':[{'type':'output_text','text':text,'annotations':[]}]}
            if index==1 and not final_only:
                item={'type':'function_call','id':'fc_original','call_id':'call_original','name':'exec_command',
                    'arguments':json.dumps({'cmd':"Set-Content -LiteralPath 'kept.txt' -Value 'ORIGINAL_WORK_BEFORE_STEER'; Write-Output 'ORIGINAL_EXEC_DONE'"}),
                    'status':'completed'}
            else:item=message('ORIGINAL_FINAL' if index==1 else 'GUIDANCE_APPLIED')
            response={'id':f'resp{index}','object':'response','model':core.MODEL,'status':'in_progress','output':[]}
            events=[{'type':'response.created','response':response}]
            if index==1:
                events += [{'type':'response.output_item.added','output_index':0,'item':{'type':'reasoning','id':'r1','status':'in_progress'}},
                    {'type':'response.reasoning_text.delta','item_id':'r1','output_index':0,'content_index':0,'delta':'WORK_BEFORE_STEER '},
                    {'type':'response.reasoning_text.delta','item_id':'r1','output_index':0,'content_index':0,'delta':'WORK_AFTER_STEER '},
                    {'type':'response.output_item.done','output_index':0,'item':{'type':'reasoning','id':'r1','status':'completed',
                        'content':[{'type':'reasoning_text','text':'WORK_BEFORE_STEER WORK_AFTER_STEER '}]}}]
            out_index=1 if index==1 else 0
            events.append({'type':'response.output_item.added','output_index':out_index,'item':{**item,'status':'in_progress'}})
            if item['type']=='message':events.append({'type':'response.output_text.delta','item_id':item['id'],'output_index':out_index,'content_index':0,'delta':item['content'][0]['text']})
            events += [{'type':'response.output_item.done','output_index':out_index,'item':item},
                {'type':'response.completed','response':{**response,'status':'completed','output':[item],
                    'usage':{'input_tokens':1000,'output_tokens':30,'total_tokens':1030}}}]
            ids=set();converted=[out for e in events for out in adapt_event(e,names,ids,routes)]
            chunks=[('data: '+json.dumps(e)+'\n\n').encode() for e in converted]
            self.send_response(200);self.send_header('Content-Type','text/event-stream')
            self.send_header('Content-Length',str(sum(map(len,chunks))));self.end_headers()
            try:
                for payload in chunks:
                    self.wfile.write(payload);self.wfile.flush()
                    if index==1 and b'WORK_BEFORE_STEER ' in payload:
                        first_open.set()
                        if not release.wait(25):raise AssertionError('Steering fixture timed out')
                    if index==1 and b'WORK_AFTER_STEER ' in payload:stream_after_steer.set()
            except (BrokenPipeError,ConnectionResetError,OSError):stream_closed_early.set()
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start();rpc=None
    def pump(predicate,timeout=25):
        deadline=time.monotonic()+timeout
        while not predicate():
            if time.monotonic()>deadline:raise AssertionError('Native steering timed out')
            try:notifications.append(events.get(timeout=.05))
            except queue.Empty:pass
    try:
        temporary=tempfile.TemporaryDirectory(prefix='steering-native24-',dir=original/'verification-project')
        folder=temporary.name
        try:
            root=Path(folder);(root/'engine').mkdir();os.link(original/'engine/codex.exe',root/'engine/codex.exe')
            events=queue.Queue();settings={**core.load_settings(),'project':str(root)}
            with patch.object(core,'ROOT',root),patch.object(core.Path,'home',return_value=root/'no-home'):
                core.prepare(settings)
                config=root/'codex-home/config.toml';config.write_text(config.read_text().replace('127.0.0.1:8081',f'127.0.0.1:{server.server_port}'))
                rpc=core.RpcClient(events.put)
                thread=rpc.request('thread/start',{'cwd':str(root),'model':core.MODEL,'modelProvider':'qwen_local',
                    'sandbox':'danger-full-access','approvalPolicy':'never','config':core.engine_config(settings)})['thread']
                turn=rpc.request('turn/start',{'threadId':thread['id'],'input':[{'type':'text','text':'Finish the original work.'}]})['turn']
                pump(first_open.is_set)
                accepted=rpc.request('turn/steer',{'threadId':thread['id'],'expectedTurnId':turn['id'],
                    'input':[{'type':'text','text':'STEER_DOWNLOAD_TO_G_KEEP_ORIGINAL_OUTPUT'}]})
                assert accepted['turnId']==turn['id']
                release.set()
                pump(lambda:any(e.get('method')=='turn/completed' and e.get('params',{}).get('turn',{}).get('id')==turn['id'] for e in notifications))
                assert len(requests)==2,len(requests)
                assert 'STEER_DOWNLOAD_TO_G_KEEP_ORIGINAL_OUTPUT' in json.dumps(requests[1]['input'])
                assert stream_after_steer.is_set() and not stream_closed_early.is_set()
                assert sum(e.get('method')=='turn/started' for e in notifications)==1
                ending=next(e['params']['turn'] for e in notifications if e.get('method')=='turn/completed')
                assert ending['status']=='completed',ending
                if not final_only:
                    assert (root/'kept.txt').read_text().strip()=='ORIGINAL_WORK_BEFORE_STEER'
                    assert 'ORIGINAL_EXEC_DONE' in json.dumps(requests[1]['input'])
                else:assert 'ORIGINAL_FINAL' in json.dumps(requests[1]['input'])
                result={'ok':True,'first_response_final_only':final_only,'same_native_turn':True,
                    'original_stream_continues_after_steer':True,'guidance_in_next_provider_request':True,
                    'original_tool_executed':not final_only,'no_new_turn_started':True,'real_model_requests':0}
                report=original/('verification-steering24-final-only.json' if final_only else 'verification-steering24-native.json')
                report.write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result),flush=True)
                rpc.close();rpc=None
        finally:
            if rpc:rpc.close();rpc=None
            temporary.cleanup()
    finally:
        release.set()
        if rpc:rpc.close()
        server.shutdown();server.server_close();worker.join(timeout=2)

if __name__=='__main__':
    if '--native' in sys.argv:native_check('--final-only' in sys.argv)
    else:unittest.main(verbosity=2)
