"""Install only the workbench referenced by the existing desktop launcher."""
import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import urllib.request
import core
from profiles26_guard import guard

SOURCE=Path(__file__).resolve().parent
STAGE=core.ROOT/'staging/directive-profiles-26-ready/MyCodex'
TARGET=core.ROOT/'app/MyCodex-profiles26'
LAUNCHER=Path.home()/'Desktop/我的Codex.cmd'
SHELL=Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/native/powershell/pwsh.exe'
FILES=('settings.json','instructions.md','model-catalog.json','codex-home/config.toml')


def run(args,timeout=180):
    result=subprocess.run([str(x) for x in args],cwd=SOURCE,creationflags=core.NO_WINDOW,
        capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=timeout)
    if result.returncode:raise RuntimeError(result.stderr[-2500:] or result.stdout[-2500:] or 'Subprocess failed')
    return result


def processes():
    cmd="Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'MyCodex.exe' } | Select-Object ProcessId,ExecutablePath,@{Name='Gateway';Expression={$_.CommandLine -match '--gateway'}} | ConvertTo-Json -Compress"
    data=run([SHELL,'-NoProfile','-Command',cmd],30).stdout.strip()
    value=json.loads(data) if data else []
    return value if isinstance(value,list) else [value]


def health():
    req=urllib.request.Request('http://127.0.0.1:8081/health',headers={'Authorization':'Bearer '+core.load_settings()['api_key']})
    with urllib.request.urlopen(req,timeout=3) as response:return json.load(response)


def wait_health(version):
    until=time.monotonic()+30
    while time.monotonic()<until:
        try:
            if health().get('adapter_version')==version:return
        except (OSError,ValueError):pass
        time.sleep(.25)
    raise RuntimeError('Local interface did not become ready')


def assert_idle():
    state=guard()
    if not state['safe']:raise RuntimeError(state['reason'])


def stop_gateway(pid,executable):
    # Validate the executable again inside the process operation, including PID reuse.
    path=str(executable).replace("'","''")
    cmd=f"$taskProc=Get-CimInstance Win32_Process -Filter 'ProcessId={int(pid)}'; if($taskProc -and $taskProc.ExecutablePath -eq '{path}') {{ Stop-Process -Id {int(pid)} }}"
    run([SHELL,'-NoProfile','-Command',cmd],20)


def main():
    report={'installed':False,'phase':'preflight','adapter_version':core.ADAPTER_VERSION}
    backup=None;changed=False;gateway=None;old_exe=None
    with core.model_lock():
        try:
            assert_idle()
            settings=core.load_settings();live=core.active_model()
            if core.selected_model(settings)!=core.MODEL or live.get('model')!=core.MODEL:
                raise RuntimeError('User model selection changed; no model was switched')
            if core.server_ready():
                assert Path(core.api('/props')['model_path']).resolve()==core.model_file(core.MODEL).resolve()
            elif core.owned_process(live.get('pid',0)):
                raise RuntimeError('Model is starting; current work was preserved')
            old_text=LAUNCHER.read_text(encoding='utf-8-sig')
            import re
            match=re.search(r'"(D:\\LocalCodex\\app\\[^"\r\n]+\\MyCodex\.exe)"',old_text,re.I)
            if not match:raise RuntimeError('Desktop launcher no longer selects the original D: workbench')
            old_exe=Path(match[1])
            assert old_exe.resolve().is_relative_to((core.ROOT/'app').resolve())
            for name in ('verification-profiles26-offline.json','verification-build26.json','verification-draft-native26.json'):
                if not json.loads((core.ROOT/name).read_text(encoding='utf-8')).get('ok'):
                    raise RuntimeError('Release verification is incomplete: '+name)
            build=json.loads((core.ROOT/'verification-build26.json').read_text(encoding='utf-8'))
            exe=STAGE/'MyCodex.exe'
            if hashlib.sha256(exe.read_bytes()).hexdigest()!=build['executable_sha256']:
                raise RuntimeError('Staged executable changed since verification')
            active=processes()
            if any(Path(p['ExecutablePath'])==old_exe and not p['Gateway'] for p in active):
                raise RuntimeError('Original desktop is open; current work was preserved')
            backup=core.ROOT/'backups'/('before-profiles26-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
            backup.mkdir(parents=True)
            for name in FILES:
                destination=backup/name;destination.parent.mkdir(parents=True,exist_ok=True)
                shutil.copy2(core.ROOT/name,destination)
            shutil.copytree(core.ROOT/'conversations',backup/'conversations')
            shutil.copy2(LAUNCHER,backup/LAUNCHER.name)
            for name in ('jack-local.config.toml','huihui-local.config.toml'):
                path=Path.home()/'.codex'/name
                if path.exists():shutil.copy2(path,backup/name)
            assert_idle()
            for p in active:
                if Path(p['ExecutablePath'])==old_exe and p['Gateway']:
                    stop_gateway(p['ProcessId'],old_exe)
            changed=True
            if TARGET.exists():
                if hashlib.sha256((TARGET/'MyCodex.exe').read_bytes()).hexdigest()!=build['executable_sha256']:
                    raise RuntimeError('Existing target contains a different build')
            else:shutil.copytree(STAGE,TARGET)
            new_exe=TARGET/'MyCodex.exe'
            run([new_exe,'--prepare-directive-profiles'],60)
            actual=core.load_settings()
            additions={'directive_mode','jack_xml_enabled','directive_custom_tag','directive_custom_text','emotion_mode','emotion_strength'}
            if {k:v for k,v in actual.items() if k not in additions}!={k:v for k,v in settings.items() if k not in additions}:
                raise RuntimeError('Unrelated settings changed')
            assert (core.ROOT/'instructions.md').read_bytes()==(backup/'instructions.md').read_bytes()
            gateway=subprocess.Popen([str(new_exe),'--gateway'],creationflags=core.NO_WINDOW)
            wait_health(core.ADAPTER_VERSION)
            core._start_model(core.MODEL,live['context'],True,live.get('context_limit'))
            restored=core.active_model()
            for key in ('model','context','context_limit','backend','cpu_offload','gpu_layers','kv_cache_location','reasoning_budget','performance_mode','speculative_type'):
                if restored.get(key)!=live.get(key):raise RuntimeError('Runtime policy changed: '+key)
            run([sys.executable,'-X','utf8',SOURCE/'verify_profiles26_runtime.py'],330)
            LAUNCHER.write_text('@echo off\nstart "" "'+str(new_exe)+'"\n',encoding='ascii')
            report.update(installed=True,phase='complete',executable=str(new_exe),backup=str(backup),
                gateway_pid=gateway.pid,default_directive='obedient',emotion_mode='off',work_context=76800,
                auto_compact=63488,unlimited_thinking=True,weights_modified=False,real_model_verified=True,
                time=datetime.datetime.now().isoformat())
        except Exception as error:
            report.update(phase='failed',error=str(error),backup=str(backup) if backup else None)
            if changed:
                if gateway and gateway.poll() is None:gateway.terminate();gateway.wait(timeout=10)
                for name in FILES:shutil.copy2(backup/name,core.ROOT/name)
                shutil.copy2(backup/LAUNCHER.name,LAUNCHER)
                for name in ('jack-local.config.toml','huihui-local.config.toml'):
                    if (backup/name).exists():shutil.copy2(backup/name,Path.home()/'.codex'/name)
                try:
                    core._start_model(core.selected_model(),live['context'],True,live.get('context_limit'))
                    subprocess.Popen([str(old_exe),'--gateway'],creationflags=core.NO_WINDOW)
                    report['original_runtime_restored']=True
                except Exception as restore:report['restore_error']=str(restore)
            raise
        finally:
            (core.ROOT/'deployment-profiles26.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:report[k] for k in ('installed','phase','executable','default_directive','emotion_mode')},ensure_ascii=False))
    subprocess.Popen([str(TARGET/'MyCodex.exe'),'--show-model-options'],creationflags=core.NO_WINDOW)


if __name__=='__main__':main()
