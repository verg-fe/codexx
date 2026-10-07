import json
import queue
import subprocess
import time
import core

core.start_gateway()
project=core.ROOT/'verification-project'
(project/'patch_probe.py').write_text('def double(x):\n    return x + 1\n',encoding='utf-8')
events=queue.Queue()
rpc=core.RpcClient(events.put)
changes=[]
commands=[]
try:
    thread=rpc.request('thread/start',{'cwd':str(project),'approvalPolicy':'never','sandbox':'workspace-write'})['thread']['id']
    rpc.request('turn/start',{'threadId':thread,'effort':'low','input':[{'type':'text','text':'读取 patch_probe.py。必须调用 apply_patch 工具把 double(x) 修复为返回 x 的两倍，不要用 shell 写文件。之后执行 python -c "from patch_probe import double; assert double(7)==14" 验证。'}]})
    deadline=time.monotonic()+600
    while time.monotonic()<deadline:
        try:
            event=events.get(timeout=30)
        except queue.Empty:
            print('Waiting for patch test...',flush=True)
            continue
        method=event.get('method','')
        if 'id' in event and method:
            rpc.send({'id':event['id'],'result':{'decision':'decline'}})
        if method=='item/completed':
            item=event['params']['item']
            print(item.get('type'),str(item.get('command',item.get('changes','')))[:600],flush=True)
            if item.get('type')=='fileChange': changes.extend(item.get('changes',[]))
            if item.get('type')=='commandExecution': commands.append(item.get('command',''))
        if method=='turn/completed':
            assert not event['params']['turn'].get('error'), str(event['params']['turn'].get('error'))
            break
    assert changes, 'No native apply_patch file change event'
    result=subprocess.run(['python','-c','from patch_probe import double; assert double(7)==14'],cwd=project,creationflags=core.NO_WINDOW)
    assert result.returncode==0
    assert any('assert double(7)' in command for command in commands)
    report_path=core.ROOT/'verification.json'
    report=json.loads(report_path.read_text(encoding='utf-8'))
    report['checks']['native_apply_patch']={'ok':True,'changes':changes,'commands':commands}
    report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Native Codex apply_patch round trip passed.',flush=True)
finally:
    rpc.close()
