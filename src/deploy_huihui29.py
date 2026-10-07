"""Install the new option in the original desktop; keep every model stopped."""
from datetime import datetime
import hashlib,json,shutil,subprocess,time,urllib.request
from pathlib import Path
import core

def main():
    root=core.ROOT;stage=root/'staging/huihui-option-29-ready/MyCodex';target=root/'app/MyCodex-huihui29'
    stopped=json.loads((root/'huihui29-stop-status.json').read_text());backup=Path(stopped['backup'])
    report={'installed':False,'backup':str(backup),'adapter_version':core.ADAPTER_VERSION}
    saved=(root/'settings.json').read_bytes();old_exe=root/'app/MyCodex-emotion28/MyCodex.exe'
    with core.model_lock():
        assert not core.server_ready(),'A model was restarted; deployment must stop.'
        assert json.loads((root/'verification-huihui29-offline.json').read_text())['ok']
        built=json.loads((root/'verification-build29.json').read_text())
        assert built['ok'] and hashlib.sha256((stage/'MyCodex.exe').read_bytes()).hexdigest()==built['executable_sha256']
        if (root/'conversations').exists():shutil.copytree(root/'conversations',backup/'conversations',dirs_exist_ok=True)
        # The user cancelled this old migration task and authorized closing Jack.
        # Only stop the captured old desktop, its gateway and orphaned history child.
        old_path=str(old_exe).replace("'","''")
        script=f"foreach($id in @(14316,11904,8756)) {{ $p=Get-CimInstance Win32_Process -Filter ('ProcessId='+$id); if($p -and $p.ExecutablePath -eq '{old_path}') {{ Stop-Process -Id $p.ProcessId }} }}"
        done=subprocess.run(['powershell','-NoProfile','-Command',script],creationflags=core.NO_WINDOW,capture_output=True,text=True,timeout=20)
        if done.returncode:raise RuntimeError('Old workbench could not close: '+done.stderr[-1000:])
        if (root/'settings.json').read_bytes()!=saved:raise RuntimeError('Settings changed during deployment')
        if target.exists():raise RuntimeError('New release directory already exists')
        shutil.copytree(stage,target)
        settings=core.load_settings();settings['model']=core.HUIHUI_IQ3S_MODEL
        settings.setdefault('model_contexts',{})[core.HUIHUI_IQ3S_MODEL]=core.WORK_CONTEXT
        # Jack control vectors are specific to Jack weights; current channels are off.
        settings['emotion_mode']='off';settings['emotion_secondary_mode']='off'
        core.prepare(settings)
        exe=target/'MyCodex.exe';gateway=subprocess.Popen([str(exe),'--gateway'],creationflags=core.NO_WINDOW)
        until=time.monotonic()+25
        while True:
            try:
                req=urllib.request.Request('http://127.0.0.1:8081/health',headers={'Authorization':'Bearer '+settings['api_key']})
                with urllib.request.urlopen(req,timeout=3) as response:health=json.load(response)
                if health.get('adapter_version')==core.ADAPTER_VERSION:break
            except OSError:pass
            if time.monotonic()>until:raise RuntimeError('Updated gateway did not become ready')
            time.sleep(.25)
        launcher=Path.home()/'Desktop/我的Codex.cmd'
        launcher.write_text('@echo off\nstart "" "'+str(exe)+'" --no-auto-model\n',encoding='ascii')
        report.update(installed=True,executable=str(exe),gateway_pid=gateway.pid,
            default_model=core.HUIHUI_IQ3S_MODEL,context=list(core.engine_limits(settings)),
            jack_stopped=not core.server_ready(),time=datetime.now().astimezone().isoformat())
        (root/'deployment-huihui29.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False),flush=True)

if __name__=='__main__':main()
