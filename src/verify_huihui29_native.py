"""One bounded private Codex file task; restore the user's stopped model state."""
import json,os,queue,time
from pathlib import Path
from unittest.mock import patch
import core

def main():
    daily=core.ROOT;saved=(daily/'settings.json').read_bytes();settings=core.load_settings()
    root=daily/'verification-project/huihui29-native';root.mkdir(exist_ok=True)
    (root/'engine').mkdir(exist_ok=True)
    if not (root/'engine/codex.exe').exists():os.link(daily/'engine/codex.exe',root/'engine/codex.exe')
    project=root/'project';project.mkdir(exist_ok=True);file=project/'readiness.txt'
    assert not file.exists(),'Do not reuse an existing verification result.'
    report={'ok':False,'phase':'loading','file':str(file),'scope':'One private native task, 90-second wait; no daily reasoning cap.'}
    path=daily/'verification-huihui29-native.json';events=queue.Queue();rpc=None;turn=None;thread=None
    def save():path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    try:
        save();assert not core.server_ready()
        core.start_model(core.HUIHUI_IQ3S_MODEL,core.WORK_CONTEXT,wait=True)
        candidate={**settings,'project':str(project)}
        with patch.object(core,'ROOT',root),patch.object(core.Path,'home',return_value=root/'no-home'):
            core.prepare(candidate);rpc=core.RpcClient(events.put)
        report.update(phase='native_task');save()
        thread=rpc.request('thread/start',{'cwd':str(project),'model':core.HUIHUI_IQ3S_MODEL,
            'modelProvider':'qwen_local','sandbox':'danger-full-access','approvalPolicy':'never',
            'config':core.engine_config(settings)})['thread']
        turn=rpc.request('turn/start',{'threadId':thread['id'],'input':[{'type':'text','text':
            'Use one exec_command call to run PowerShell Set-Content -LiteralPath readiness.txt -Value HUIHUI29_OK -Encoding utf8; Get-Content -LiteralPath readiness.txt. Then reply with the verified file path. This is a tiny local readiness check; act directly.'}]})['turn']
        report.update(thread_id=thread['id'],turn_id=turn['id']);save()
        until=time.monotonic()+90;seen=[];completed=None
        while time.monotonic()<until:
            try:event=events.get(timeout=.2)
            except queue.Empty:continue
            seen.append(event)
            if event.get('method')=='turn/completed':completed=event.get('params',{}).get('turn');break
        if completed is None:
            rpc.request('turn/interrupt',{'threadId':thread['id'],'turnId':turn['id']},timeout=10)
            report.update(phase='timeout',error='Private native test exceeded its 90-second wait; interrupted only this test.')
        else:
            report.update(phase='complete',native_status=completed.get('status'),file_exists=file.exists(),
                file_content=file.read_text(encoding='utf-8-sig').strip() if file.exists() else None)
            report['ok']=completed.get('status')=='completed' and report['file_content']=='HUIHUI29_OK'
        (root/'events.json').write_text(json.dumps(seen,ensure_ascii=False,indent=2),encoding='utf-8')
    except Exception as error:report.update(phase='failed',error=type(error).__name__+': '+str(error))
    finally:
        if rpc:rpc.close()
        live=core.active_model()
        if live.get('model')==core.HUIHUI_IQ3S_MODEL:core.stop_model()
        report['all_models_stopped']=not core.server_ready()
        report['daily_settings_unchanged']=saved==(daily/'settings.json').read_bytes()
        save();print(json.dumps(report,ensure_ascii=False),flush=True)

if __name__=='__main__':main()
