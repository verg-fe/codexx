"""Increase every saved context by 20K once and install the original desktop."""
from datetime import datetime
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import time
import urllib.request

import core


def powershell(script):
    result = subprocess.run(['powershell', '-NoProfile', '-Command', script],
        capture_output=True, text=True, creationflags=core.NO_WINDOW, timeout=30)
    if result.returncode:
        raise RuntimeError(result.stderr[-1000:])
    return result.stdout.strip()


def check_idle():
    if core.server_ready() or (core.ROOT/'model.pid').exists() or (core.ROOT/'active-model.json').exists():
        raise RuntimeError('A model was started; leave the current task untouched.')
    path = core.ROOT/'generation-status.json'
    if path.exists() and json.loads(path.read_text(encoding='utf-8')).get('phase') not in (None, 'finished', 'failed', 'cancelled'):
        raise RuntimeError('Generation is active; leave the current task untouched.')


def health(settings):
    request = urllib.request.Request('http://127.0.0.1:8081/health',
        headers={'Authorization': 'Bearer '+settings['api_key']})
    with urllib.request.urlopen(request, timeout=3) as response:
        return json.load(response)


def main():
    root = core.ROOT
    report_path = root/'deployment-context30.json'
    if report_path.exists() and json.loads(report_path.read_text())['installed']:
        print('Already installed; no second context increment.')
        return
    backup = Path(json.loads((root/'context30-backup.json').read_text())['backup'])
    base_bytes = (backup/'settings.json').read_bytes()
    settings = json.loads(base_bytes)
    expected = {**settings, 'model_contexts': {
        name: core.context_for(settings, name)+20480 for name in core.MODELS},
        'work_context': settings.get('work_context', 76800)+20480}
    assert all(value <= core.MAX_CONTEXT for value in expected['model_contexts'].values())
    assert core.engine_limits(expected) == (97280, 83968)
    stage = root/'staging/context-plus20-30-ready/MyCodex'
    target = root/'app/MyCodex-context30'
    old_exe = root/'app/MyCodex-huihui29/MyCodex.exe'
    launcher = Path.home()/'Desktop/我的Codex.cmd'
    report = {'installed': False, 'backup': str(backup), 'adapter_version': core.ADAPTER_VERSION}
    new_gateway = None
    closed_old = False
    changed_settings = False
    try:
        with core.model_lock():
            check_idle()
            assert (root/'settings.json').read_bytes() == base_bytes, 'User settings changed since backup'
            assert json.loads((root/'verification-context30-offline.json').read_text())['ok']
            built = json.loads((root/'verification-build30.json').read_text())
            assert built['ok'] and hashlib.sha256((stage/'MyCodex.exe').read_bytes()).hexdigest() == built['executable_sha256']
            assert not target.exists(), 'Release directory already exists'
            shutil.copytree(stage, target)
            shutil.copytree(root/'conversations', backup/'conversations', dirs_exist_ok=True)
            old_path = str(old_exe).replace("'", "''")
            # A normal window close preserves the user's transcript and native state.
            powershell("$ErrorActionPreference='Stop'; $apps=@(Get-CimInstance Win32_Process | "
                f"Where-Object {{ $_.ExecutablePath -eq '{old_path}' -and $_.CommandLine -notmatch '--gateway|--history-server|--signal-model-console' }}); "
                "foreach($app in $apps) { $p=Get-Process -Id $app.ProcessId -ErrorAction SilentlyContinue; "
                "if($p) { $null=$p.CloseMainWindow(); if(-not $p.WaitForExit(12000)) { throw 'The workbench did not close normally; preserve it.' } } }")
            closed_old = True
            check_idle()
            assert (root/'settings.json').read_bytes() == base_bytes, 'User settings changed during close'
            powershell("$ErrorActionPreference='Stop'; Get-CimInstance Win32_Process | "
                f"Where-Object {{ $_.ExecutablePath -eq '{old_path}' -and $_.CommandLine -match '--gateway' }} | "
                "ForEach-Object { Stop-Process -Id $_.ProcessId }")
            changed_settings = True
            core.prepare(expected)
            exe = target/'MyCodex.exe'
            new_gateway = subprocess.Popen([str(exe), '--gateway'], creationflags=core.NO_WINDOW)
            deadline = time.monotonic()+25
            while time.monotonic() < deadline:
                try:
                    if health(expected).get('adapter_version') == core.ADAPTER_VERSION:
                        break
                except OSError:
                    pass
                time.sleep(.25)
            else:
                raise RuntimeError('Updated local interface did not become ready')
            launcher.write_text('@echo off\nstart "" "'+str(exe)+'" --no-auto-model\n', encoding='ascii')
            report.update(installed=True, executable=str(exe), gateway_pid=new_gateway.pid,
                increment_tokens=20480, model_contexts=expected['model_contexts'],
                work_context=core.engine_limits(expected)[0], compact=core.engine_limits(expected)[1],
                max_context=core.MAX_CONTEXT, gpu_context_limit=core.GPU_CONTEXT_LIMIT,
                reasoning_budget=core.REASONING_BUDGET, desktop_auto_load=False,
                selected_model=expected['model'], models_stopped=not core.server_ready(),
                time=datetime.now().astimezone().isoformat())
        ui = subprocess.Popen([report['executable'], '--show-model-options', '--no-auto-model'],
            creationflags=core.NO_WINDOW)
        report['ui_pid'] = ui.pid
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(report, ensure_ascii=False))
    except Exception as error:
        if new_gateway is not None and new_gateway.poll() is None:
            new_gateway.terminate()
            new_gateway.wait(timeout=10)
        if changed_settings:
            (root/'settings.json').write_bytes(base_bytes)
            for name in ['model-catalog.json', 'instructions.md']:
                shutil.copy2(backup/name, root/name)
            for profile in (backup/'codex-home').glob('*.toml'):
                shutil.copy2(profile, root/'codex-home'/profile.name)
            for profile in (backup/'user-profiles').glob('*.toml'):
                shutil.copy2(profile, Path.home()/'.codex'/profile.name)
            shutil.copy2(backup/'我的Codex.cmd', launcher)
        if closed_old:
            try:
                health(settings)
            except OSError:
                subprocess.Popen([str(old_exe), '--gateway'], creationflags=core.NO_WINDOW)
            subprocess.Popen([str(old_exe), '--show-model-options', '--no-auto-model'], creationflags=core.NO_WINDOW)
        report.update(error=str(error).replace(settings['api_key'], '[redacted]'),
            time=datetime.now().astimezone().isoformat())
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        raise RuntimeError(report['error']) from None


if __name__ == '__main__':
    main()
