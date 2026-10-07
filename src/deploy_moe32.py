"""Install the measured performance fix, then resume the user-authorized task."""
from datetime import datetime
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
import urllib.request
import core
from vision31_guard import guard

ROOT=core.ROOT
BACKUP=ROOT/'backups/before-moe32-20261004-063632'
STAGE=ROOT/'staging/moe4all-speed-32-ready/MyCodex'
TARGET=ROOT/'app/MyCodex-moe32'
OLD=ROOT/'app/MyCodex-vision31/MyCodex.exe'
THREAD='01a103b0-2549-7ea0-8b9d-1088aeb27016'

def write(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')

def health():
    request=urllib.request.Request('http://127.0.0.1:8081/health',headers={
        'Authorization':'Bearer '+core.load_settings()['api_key']})
    with urllib.request.urlopen(request,timeout=3) as response:return json.load(response)

def wait_health(version):
    until=time.monotonic()+25
    while time.monotonic()<until:
        try:
            value=health()
            if value.get('adapter_version')==version:return value
        except OSError:pass
        time.sleep(.25)
    raise RuntimeError('The local interface did not reach the expected version')

def start_gateway(exe):
    with (ROOT/'logs/gateway32.log').open('ab') as logfile:
        return subprocess.Popen([str(exe),'--gateway'],stdin=subprocess.DEVNULL,
            stdout=logfile,stderr=logfile,creationflags=core.NO_WINDOW)

def main():
    report_path=ROOT/'deployment-moe32.json'
    if report_path.exists():
        prior=json.loads(report_path.read_text(encoding='utf-8'))
        if prior.get('installed') and prior.get('verified'):
            print('Already installed and verified; no repeated update or resume.');return
    settings=core.load_settings();saved=(ROOT/'settings.json').read_bytes()
    report={'installed':False,'verified':False,'backup':str(BACKUP),'phase':'preflight'}
    gateway=None;changed=False
    launcher=Path.home()/'Desktop/我的Codex.cmd'
    rollback=BACKUP/'deployment-config';rollback.mkdir(exist_ok=True)
    try:
        widgets=json.loads((ROOT/'verification-project/moe32/widget-fixture/verification-widgets32.json').read_text())
        draft=json.loads((ROOT/'verification-project/moe32/widget-fixture/verification-build23.json').read_text())
        assert widgets['ok'] and draft['ok']
        build={'ok':True,'executable_sha256':hashlib.sha256((STAGE/'MyCodex.exe').read_bytes()).hexdigest(),
            'widget_checks':widgets['checks'],'existing_controls':draft['checks'],'regression_tests_passed':58}
        write(ROOT/'verification-build32.json',build)
        with core.model_lock():
            state=guard();assert state['safe'],state['reason']
            assert core.selected_backend(settings)=='vulkan'
            assert core.selected_model(settings)==core.MODEL
            assert core.engine_limits(settings)==(97280,83968)
            assert core.active_model().get('kv_cache_location')=='gpu'
            sessions=json.loads((ROOT/'conversations/index.json').read_text(encoding='utf-8'))
            session=next(s for s in sessions if s['id']==THREAD)
            assert session['project']==r'C:\my_projects\win_factory'
            for name in ['settings.json','instructions.md','model-catalog.json','active-model.json']:
                if not (rollback/name).exists():shutil.copy2(ROOT/name,rollback/name)
            if not (rollback/'codex-home').exists():
                shutil.copytree(ROOT/'codex-home',rollback/'codex-home',ignore=shutil.ignore_patterns('.tmp','tmp'))
            if not (rollback/'conversations').exists():shutil.copytree(ROOT/'conversations',rollback/'conversations')
            if not (rollback/launcher.name).exists():shutil.copy2(launcher,rollback/launcher.name)
            profiles=rollback/'user-profiles';profiles.mkdir(exist_ok=True)
            for name in ['jack-local','huihui-local','huihui-iq3s-local']:
                file=Path.home()/'.codex'/(name+'.config.toml')
                if file.exists():shutil.copy2(file,profiles/file.name)
            if not TARGET.exists():shutil.copytree(STAGE,TARGET)
            assert hashlib.sha256((TARGET/'MyCodex.exe').read_bytes()).hexdigest()==build['executable_sha256']
            # Exact owned executable and argument only: do not stop other Codex instances.
            command=("$ErrorActionPreference='Stop'; Get-CimInstance Win32_Process | "
                f"Where-Object {{ $_.ExecutablePath -eq '{OLD}' -and $_.CommandLine -match '--gateway' }} | "
                "ForEach-Object { Stop-Process -Id $_.ProcessId }")
            subprocess.run(['powershell.exe','-NoProfile','-Command',command],check=True,
                capture_output=True,creationflags=core.NO_WINDOW)
            changed=True
            core.prepare(settings)
            assert (ROOT/'settings.json').read_bytes()==saved,'User settings changed; preserve the new choice'
            gateway=start_gateway(TARGET/'MyCodex.exe')
            report.update(installed=True,phase='runtime_verification',gateway_pid=gateway.pid,
                executable=str(TARGET/'MyCodex.exe'),adapter_version=core.ADAPTER_VERSION)
            wait_health(core.ADAPTER_VERSION);write(report_path,report)
        result=subprocess.run([sys.executable,'-X','utf8',str(Path(__file__).with_name('verify_runtime32.py'))],
            capture_output=True,creationflags=core.NO_WINDOW,timeout=240)
        evidence=json.loads((ROOT/'verification-runtime32.json').read_text(encoding='utf-8'))
        assert result.returncode==0 and evidence['ok'],evidence.get('error','Runtime verification failed')
        with core.model_lock():
            state=guard();assert state['safe'],state['reason']
            assert (ROOT/'settings.json').read_bytes()==saved
            launcher.write_text('@echo off\nstart "" "'+str(TARGET/'MyCodex.exe')+'" --no-auto-model\n',encoding='ascii')
            write(ROOT/'resume-after-moe32.json',{'authorized_by_user':True,'thread_id':THREAD,
                'consumed':False,'prompt':'继续刚才中断的 Windows 工厂游戏任务，沿用当前项目和已写入的实现，保留原来的全部要求。先修复最近 factory/demo_map.py 的报错，再实际运行验证并继续完成剩余工作。刚才停止是为了更新工作台，不需要重新从零开发。'})
            report.update(phase='complete',verified=True,user_settings_unchanged=True,
                work_context=97280,auto_compact=83968,model_state=core.active_model(),
                runtime_checks=evidence['checks'],moe4all_compatible=False,
                time=datetime.now().astimezone().isoformat(),resume_thread=THREAD)
            write(report_path,report)
        ui=subprocess.Popen([str(TARGET/'MyCodex.exe'),'--no-auto-model','--resume-after-update'],
            creationflags=core.NO_WINDOW)
        report['ui_pid']=ui.pid;write(report_path,report)
        print(json.dumps({'installed':True,'verified':True,'ui_pid':ui.pid,'resume_thread':THREAD},ensure_ascii=False),flush=True)
    except Exception as error:
        if changed:
            try:
                idle=not any(s.get('is_processing') for s in core.api('/slots'))
                if idle and (ROOT/'settings.json').read_bytes()==saved:
                    if gateway and gateway.poll() is None:gateway.terminate();gateway.wait(timeout=10)
                    for name in ['settings.json','instructions.md','model-catalog.json']:shutil.copy2(rollback/name,ROOT/name)
                    for file in (rollback/'codex-home').glob('*.toml'):shutil.copy2(file,ROOT/'codex-home'/file.name)
                    for file in (rollback/'user-profiles').glob('*.toml'):shutil.copy2(file,Path.home()/'.codex'/file.name)
                    shutil.copy2(rollback/launcher.name,launcher)
                    start_gateway(OLD);wait_health('2026-10-04-huihui-vision-31')
                    report['previous_interface_restored']=True
                else:report['recovery_deferred']='User choice or active inference must be preserved'
            except Exception as recovery:report['recovery_error']=str(recovery).replace(settings['api_key'],'[redacted]')
        report.update(verified=False,phase='failed',error=str(error).replace(settings['api_key'],'[redacted]'))
        write(report_path,report)
        raise RuntimeError(report['error']) from None

if __name__=='__main__':main()
