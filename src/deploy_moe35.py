"""Install the checked optional RAM profile without changing the daily backend."""
import json
from pathlib import Path
import shutil
import subprocess
import time
import urllib.request
import core
from vision31_guard import guard
from verify_kv20 import native_state
from profiles26_guard import process_alive

ROOT=core.ROOT
DIR=ROOT/'verification-project/moe35-deploy'
REPORT=ROOT/'deployment-moe35.json'

def main():
    before=json.loads((DIR/'before.json').read_text(encoding='utf-8'))
    saved=(ROOT/'settings.json').read_bytes(); previous=core.active_model()
    stage=ROOT/'staging/moe-ram35-ready/MyCodex'; destination=ROOT/'app/MyCodex-moe35-final'
    assert (stage/'MyCodex.exe').is_file() and before['gui_exited'] and before['native_terminal']
    report={'installed':False,'daily_backend':'vulkan','restored':False}
    with core.model_lock():
        state=guard()
        if not state['safe'] and state['reason']=='Inference remains active':
            latest,terminal,_=native_state(Path(before['native_file']))
            assert latest==before['turn_id'] and terminal and not process_alive(before['gui_pid'])
            assert core.active_model()['pid']==before['active_model']['pid']
            assert json.loads((ROOT/'request-routing.json').read_text())['thread_id']==before['thread_id']
            core._stop_model();state=guard()
        assert state['safe'],state['reason']
        assert core.selected_backend()=='vulkan','Preserve the user choice'
        backup=ROOT/'backups/before-moe35-install'
        backup.mkdir(parents=True,exist_ok=True)
        for path in (ROOT/'settings.json',ROOT/'codex-home/config.toml',ROOT/'conversations/index.json',
                     Path(r'C:\Users\18213\Desktop\我的Codex.cmd')):
            if path.exists() and not (backup/path.name).exists():shutil.copy2(path,backup/path.name)
        query="Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'MyCodex.exe' -and $_.CommandLine -match '--gateway' } | Select-Object ProcessId,ExecutablePath | ConvertTo-Json -Compress"
        value=subprocess.run(['powershell.exe','-NoProfile','-Command',query],capture_output=True,check=True,creationflags=core.NO_WINDOW)
        rows=json.loads(value.stdout.decode('utf-8-sig')); rows=rows if isinstance(rows,list) else [rows]
        assert len(rows)==1
        row=rows[0]; path=Path(row['ExecutablePath']).resolve()
        assert path.is_relative_to((ROOT/'app').resolve())
        shutil.copytree(stage,destination,dirs_exist_ok=True)
        subprocess.run(['powershell.exe','-NoProfile','-Command',f"Stop-Process -Id {int(row['ProcessId'])}"],check=True,creationflags=core.NO_WINDOW)
        deadline=time.monotonic()+15
        while process_alive(row['ProcessId']) and time.monotonic()<deadline:time.sleep(.2)
        assert not process_alive(row['ProcessId'])
        with (ROOT/'logs/gateway35.log').open('w',encoding='utf-8') as log:
            gateway=subprocess.Popen([str(destination/'MyCodex.exe'),'--gateway'],stdout=log,stderr=log,
                stdin=subprocess.DEVNULL,creationflags=core.NO_WINDOW)
        report['gateway_pid']=gateway.pid
        deadline=time.monotonic()+30
        while time.monotonic()<deadline:
            try:
                request=urllib.request.Request('http://127.0.0.1:8081/health',
                    headers={'Authorization':'Bearer '+core.load_settings()['api_key']})
                with urllib.request.urlopen(request,timeout=2) as response:health=json.load(response)
                if health.get('adapter_version')==core.ADAPTER_VERSION:break
            except (OSError,ValueError):pass
            time.sleep(.3)
        else:raise RuntimeError('New gateway did not become ready')
        core._start_model(previous['model'],previous['context'],True,previous['context_limit'])
        report['restored']=core.server_ready();assert report['restored']
        assert (ROOT/'settings.json').read_bytes()==saved
        desktop=Path(r'C:\Users\18213\Desktop\我的Codex.cmd')
        desktop.write_text('@echo off\nstart "" "'+str(destination/'MyCodex.exe')+'" --no-auto-model\n',encoding='utf-8')
        report.update(installed=True,adapter_version=health['adapter_version'],desktop=str(destination/'MyCodex.exe'),
                      daily_settings_unchanged=True)
    resume=not before['native_was_terminal']
    if resume:
        (ROOT/'resume-after-moe32.json').write_text(json.dumps({'authorized_by_user':True,'consumed':False,
            'thread_id':before['thread_id'],'prompt':'继续刚才因模型可选配置更新暂停的原任务。沿用当前项目、全部原要求、已有文件和最新工具结果，不重复成功的操作。'},ensure_ascii=False),encoding='utf-8')
    ui=subprocess.Popen([str(destination/'MyCodex.exe'),'--no-auto-model',
        '--resume-after-update' if resume else '--show-model-options'],creationflags=core.NO_WINDOW)
    report.update(ui_pid=ui.pid,resume_requested=resume)
    REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False),flush=True)

if __name__=='__main__':main()
