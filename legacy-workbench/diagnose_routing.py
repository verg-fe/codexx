"""Inspect native Codex requests against a local error-only diagnostic endpoint."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import queue
import threading
import time
import core

report={'requests':[]}
class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def do_POST(self):
        data=json.loads(self.rfile.read(int(self.headers.get('Content-Length','0'))))
        report['requests'].append({'model':data.get('model'),'generate':data.get('generate'),
            'max_output_tokens':data.get('max_output_tokens'),'stream':data.get('stream'),
            'input_items':len(data.get('input',[])),
            'intent_model':self.headers.get('X-LocalCodex-Model'),
            'intent_context':self.headers.get('X-LocalCodex-Context')})
        body=b'{"error":{"message":"LOCAL_ROUTING_DIAGNOSTIC_STOP","type":"diagnostic"}}'
        self.send_response(503)
        self.send_header('Content-Type','application/json')
        self.send_header('Content-Length',str(len(body)))
        self.send_header('Connection','close')
        self.end_headers()
        self.wfile.write(body)

server=ThreadingHTTPServer(('127.0.0.1',8082),Handler)
threading.Thread(target=server.serve_forever,daemon=True).start()
original=core.subprocess.Popen
def diagnostic_popen(args,*a,**kw):
    if 'app-server' in args:
        args=list(args)+['-c','model_providers.qwen_local.base_url="http://127.0.0.1:8082/v1"']
    return original(args,*a,**kw)
core.subprocess.Popen=diagnostic_popen
events=queue.Queue()
rpc=None
try:
    rpc=core.RpcClient(events.put)
    cfg=rpc.request('config/read',{'includeLayers':False,'cwd':str(core.ROOT/'verification-project')})['config']
    report['config']={key:cfg.get(key) for key in ['model','model_provider','model_context_window','model_auto_compact_token_limit']}
    test=json.loads((core.ROOT/'verification-model-picker.json').read_text(encoding='utf-8'))
    tid=next(iter(test['checks'].values()))['thread_id']
    result=rpc.request('thread/resume',{'threadId':tid,'cwd':str(core.ROOT/'verification-project'),
        'model':core.HUIHUI_MODEL,'modelProvider':'qwen_local','approvalPolicy':'never','sandbox':'danger-full-access',
        'config':{'model_context_window':32768,'model_auto_compact_token_limit':27648}})
    mode=result.get('collaborationMode',{})
    report['resume']={'model':result.get('model'),'provider':result.get('modelProvider'),
        'mode_model':mode.get('settings',{}).get('model')}
    rpc.request('turn/start',{'threadId':tid,'model':core.HUIHUI_MODEL,'effort':'low',
        'collaborationMode':{'mode':'default','settings':{'model':core.HUIHUI_MODEL,
            'reasoning_effort':'low','developer_instructions':None}},
        'input':[{'type':'text','text':'LOCAL_ROUTING_DIAGNOSTIC_ONLY. Do not run tools.'}]})
    deadline=time.monotonic()+30
    while time.monotonic()<deadline:
        try: event=events.get(timeout=1)
        except queue.Empty: continue
        if event.get('method')=='turn/completed': break
finally:
    if rpc: rpc.close()
    core.subprocess.Popen=original
    server.shutdown()
    server.server_close()
    (core.ROOT/'diagnostic-routing.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=True),flush=True)
