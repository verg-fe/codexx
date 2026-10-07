"""Install verified Huihui vision support only after native user tasks finish."""
from datetime import datetime
from importlib.util import module_from_spec, spec_from_file_location
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
import urllib.request
import core
from deploy_context30 import powershell
from vision31_guard import guard


def assert_idle():
    state=guard()
    if not state['safe']:raise RuntimeError(state['reason'])


def wait_health(version):
    until=time.monotonic()+25
    while time.monotonic()<until:
        try:
            req=urllib.request.Request('http://127.0.0.1:8081/health',
                headers={'Authorization':'Bearer '+core.load_settings()['api_key']})
            with urllib.request.urlopen(req,timeout=3) as response:health=json.load(response)
            if health.get('adapter_version')==version:return
        except OSError:pass
        time.sleep(.25)
    raise RuntimeError('Local interface did not become ready')


def main():
    root=core.ROOT;report_path=root/'deployment-vision31.json'
    if report_path.exists():
        prior=json.loads(report_path.read_text(encoding='utf-8'))
        if prior.get('installed') and prior.get('verified'):
            print('Already installed and verified; no repeated reload.')
            return
    state=guard()
    if not state['safe']:
        report_path.write_text(json.dumps({'installed':False,'phase':'waiting','guard':state,
            'adapter_version':core.ADAPTER_VERSION},ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({'phase':'waiting','guard':state},ensure_ascii=False));return
    backup=Path(json.loads((root/'vision31-backup.json').read_text())['backup'])
    stage=root/'staging/huihui-vision-31-ready/MyCodex';target=root/'app/MyCodex-vision31'
    old_exe=root/'app/MyCodex-context30/MyCodex.exe';launcher=Path.home()/'Desktop/我的Codex.cmd'
    report={'installed':False,'verified':False,'phase':'preflight','backup':str(backup)}
    gateway=None;ui_closed=False;changed=False;model_changed=False;was_running=False
    settings=core.load_settings();saved=(root/'settings.json').read_bytes()
    rollback=backup/'deployment-config'
    rollback.mkdir(exist_ok=True)
    def save():report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    try:
        with core.model_lock():
            assert_idle()
            assert core.selected_model(settings)==core.HUIHUI_IQ3S_MODEL, 'User selected another model; preserve it'
            assert core.engine_limits(settings)==(97280,83968), 'User context selection changed; preserve it'
            for name in ['verification-vision31-offline.json','verification-build31.json','verification-projector31.json']:
                assert json.loads((root/name).read_text(encoding='utf-8'))['ok'], name
            build=json.loads((root/'verification-build31.json').read_text())
            assert hashlib.sha256((stage/'MyCodex.exe').read_bytes()).hexdigest()==build['executable_sha256']
            was_running=core.server_ready() or (backup/'active-model.json').exists()
            for name in ['settings.json','instructions.md','model-catalog.json']:
                if not (rollback/name).exists():shutil.copy2(root/name,rollback/name)
            (rollback/'codex-home').mkdir(exist_ok=True)
            for p in (root/'codex-home').glob('*.toml'):
                if not (rollback/'codex-home'/p.name).exists():shutil.copy2(p,rollback/'codex-home'/p.name)
            if not (rollback/'我的Codex.cmd').exists():shutil.copy2(launcher,rollback/'我的Codex.cmd')
            (rollback/'user-profiles').mkdir(exist_ok=True)
            for name in ['jack-local','huihui-local','huihui-iq3s-local']:
                p=Path.home()/'.codex'/(name+'.config.toml')
                if p.exists() and not (rollback/'user-profiles'/p.name).exists():shutil.copy2(p,rollback/'user-profiles'/p.name)
            if not target.exists():shutil.copytree(stage,target)
            assert hashlib.sha256((target/'MyCodex.exe').read_bytes()).hexdigest()==build['executable_sha256']
            old_path=str(old_exe).replace("'","''")
            powershell("$ErrorActionPreference='Stop'; $apps=@(Get-CimInstance Win32_Process | "
                f"Where-Object {{ $_.ExecutablePath -eq '{old_path}' -and $_.CommandLine -notmatch '--gateway|--history-server|--signal-model-console' }}); "
                "foreach($app in $apps) { $p=Get-Process -Id $app.ProcessId -ErrorAction SilentlyContinue; "
                "if($p) { $null=$p.CloseMainWindow(); if(-not $p.WaitForExit(12000)) { throw 'Workbench did not close normally; preserve it.' } } }")
            ui_closed=True
            assert_idle()
            assert (root/'settings.json').read_bytes()==saved, 'User settings changed during close'
            shutil.copytree(root/'conversations',backup/'conversations',dirs_exist_ok=True)
            powershell("$ErrorActionPreference='Stop'; Get-CimInstance Win32_Process | "
                f"Where-Object {{ ($_.ExecutablePath -eq '{old_path}' -or $_.ExecutablePath -eq '{str(target/'MyCodex.exe').replace(chr(39),chr(39)*2)}') -and $_.CommandLine -match '--gateway' }} | "
                "ForEach-Object { Stop-Process -Id $_.ProcessId }")
            changed=True
            core.prepare(settings)
            assert (root/'settings.json').read_bytes()==saved, 'Vision update must preserve daily settings'
            exe=target/'MyCodex.exe'
            gateway=subprocess.Popen([str(exe),'--gateway'],creationflags=core.NO_WINDOW)
            wait_health(core.ADAPTER_VERSION)
            model_changed=True
            # Already holding the cross-process file lock; its public wrapper
            # acquires a second descriptor and cannot be nested on Windows.
            core._start_model(core.HUIHUI_IQ3S_MODEL,core.WORK_CONTEXT,True,core.WORK_CONTEXT)
            assert core.api('/props')['modalities']['vision'] is True
            report.update(installed=True,phase='runtime_verification',executable=str(exe),
                gateway_pid=gateway.pid,adapter_version=core.ADAPTER_VERSION,
                work_context=97280,auto_compact=83968,user_settings_unchanged=True)
            save()
        # The image probes go through the real adapter; release the shared model lock
        # before sending them. The old user window is closed only after its turn ended.
        result=subprocess.run([sys.executable,'-X','utf8',str(Path(__file__).parent/'verify_vision31_runtime.py')],
            capture_output=True,creationflags=core.NO_WINDOW,timeout=225)
        evidence=json.loads((root/'verification-vision31-runtime.json').read_text(encoding='utf-8'))
        assert result.returncode==0 and evidence['ok'], evidence.get('error','Real vision verification failed')
        with core.model_lock():
            assert (root/'settings.json').read_bytes()==saved, 'User settings changed; preserve their selection'
            if not was_running:
                assert not any(s.get('is_processing') for s in core.api('/slots'))
                core._stop_model()
            launcher.write_text('@echo off\nstart "" "'+str(exe)+'" --no-auto-model\n',encoding='ascii')
            report.update(phase='complete',verified=True,vision_checks=evidence['checks'],
                model_was_running=was_running,model_state_preserved=True,
                jack_stopped=core.active_model().get('model')!=core.MODEL,
                time=datetime.now().astimezone().isoformat())
            save()
        ui=subprocess.Popen([str(exe),'--show-model-options','--no-auto-model'],creationflags=core.NO_WINDOW)
        report['ui_pid']=ui.pid;save()
        print(json.dumps(report,ensure_ascii=False),flush=True)
    except Exception as error:
        if changed:
            # Never undo a new user choice or stop a task begun through another client.
            try:
                inference_active=core.server_ready() and any(s.get('is_processing') for s in core.api('/slots'))
            except OSError:
                inference_active=True
            if (root/'settings.json').read_bytes()!=saved or inference_active:
                report['recovery_deferred']='Another client changed settings or began inference; preserve it'
            else:
                with core.model_lock():
                    if model_changed:core._stop_model()
                    if gateway and gateway.poll() is None:gateway.terminate();gateway.wait(timeout=10)
                    for name in ['settings.json','instructions.md','model-catalog.json']:shutil.copy2(rollback/name,root/name)
                    for p in (rollback/'codex-home').glob('*.toml'):shutil.copy2(p,root/'codex-home'/p.name)
                    for p in (rollback/'user-profiles').glob('*.toml'):shutil.copy2(p,Path.home()/'.codex'/p.name)
                    shutil.copy2(rollback/'我的Codex.cmd',launcher)
                    subprocess.Popen([str(old_exe),'--gateway'],creationflags=core.NO_WINDOW)
                    wait_health('2026-10-04-context-plus20-30')
                    if was_running:
                        spec=spec_from_file_location('core_before_vision31',backup/'core.py')
                        old=module_from_spec(spec);spec.loader.exec_module(old)
                        old._start_model(core.HUIHUI_IQ3S_MODEL,97280,True,97280)
                    report['old_release_restored']=True
        if ui_closed:subprocess.Popen([str(old_exe),'--show-model-options','--no-auto-model'],creationflags=core.NO_WINDOW)
        report.update(installed=False,verified=False,phase='failed',
            error=(type(error).__name__+': '+str(error)).replace(settings['api_key'],'[redacted]'))
        save();raise RuntimeError(report['error']) from None


if __name__=='__main__':main()
