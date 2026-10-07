"""Exercise the real private Codex/MCP protocol without calling the busy model."""
import json
import os
from pathlib import Path
import queue
import sys
import tempfile
import time
from unittest.mock import patch

import core

def main():
    frozen=Path(sys.argv[1]).resolve() if len(sys.argv)>1 else None
    report={'ok':False,'inference_requests':0,'frozen_mcp':bool(frozen)}
    original=core.ROOT
    base=(original/'verification-project').resolve();base.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='history-engine-',dir=base) as directory:
        root=Path(directory).resolve();(root/'engine').mkdir()
        assert root.is_relative_to(base)
        os.link(original/'engine/codex.exe',root/'engine/codex.exe')
        settings={'model':core.MODEL,'model_contexts':{core.MODEL:256000},'context':256000,
            'history_mode':'memory','work_context':32768,'project':str(root),'api_key':'__REDACTED__'}
        events=queue.Queue()
        with patch.object(core,'ROOT',root),patch.object(core.Path,'home',return_value=root/'no-home'):
            if frozen:
                with patch.object(core.sys,'frozen',True,create=True),patch.object(core.sys,'executable',str(frozen)):
                    core.prepare(settings)
            else:core.prepare(settings)
            rpc=core.RpcClient(events.put)
            try:
                thread=rpc.request('thread/start',{'cwd':str(root),'model':core.MODEL,
                    'modelProvider':'qwen_local','approvalPolicy':'never','sandbox':'danger-full-access',
                    'config':core.engine_config(settings)})['thread']
                deadline=time.monotonic()+25
                while True:
                    status=rpc.request('mcpServerStatus/list',{'detail':'full'})
                    if 'history_search' in json.dumps(status):break
                    if time.monotonic()>deadline:raise AssertionError('History MCP tools unavailable: '+json.dumps(status))
                    time.sleep(.25)
                thread_id=thread['id'];report['thread_id']=thread_id
                state='Objective: retain archive. Confirmed exact marker: ENGINE_RECALL_7391. Next: read it.'
                saved=rpc.request('mcpServer/tool/call',{'threadId':thread_id,'server':'local_history',
                    'tool':'history_checkpoint','arguments':{'thread_id':thread_id,'state':state}})
                assert 'ENGINE_RECALL_7391' in json.dumps(saved),str(saved)
                found=rpc.request('mcpServer/tool/call',{'threadId':thread_id,'server':'local_history',
                    'tool':'history_search','arguments':{'thread_id':thread_id,'query':'ENGINE_RECALL_7391'}})
                assert 'ENGINE_RECALL_7391' in json.dumps(found),str(found)
                print('Native MCP checkpoint and exact history search passed.',flush=True)
                rpc.request('thread/inject_items',{'threadId':thread_id,'items':[{
                    'type':'message','role':'user','content':[{'type':'input_text','text':'Protocol fixture; no inference.'}]}]})
                rpc.request('thread/unsubscribe',{'threadId':thread_id})
                rpc.request('thread/resume',{'threadId':thread_id,'cwd':str(root),'excludeTurns':True,
                    'config':core.engine_config(settings)})
                read=rpc.request('mcpServer/tool/call',{'threadId':thread_id,'server':'local_history',
                    'tool':'history_checkpoint','arguments':{'thread_id':thread_id}})
                assert 'ENGINE_RECALL_7391' in json.dumps(read),str(read)
                report.update(ok=True,checks={'native_mcp_tools_listed':True,'native_checkpoint_saved':True,
                    'native_exact_history_search':True,'resume_keeps_history_tools_and_state':True})
            finally:rpc.close()
    destination=original/('verification-history-engine-frozen.json' if frozen else 'verification-history-engine.json')
    destination.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Native history protocol verification complete.',flush=True)

if __name__=='__main__':main()
