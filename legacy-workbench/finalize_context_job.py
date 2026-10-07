"""Finish the finite benchmark: publish verified defaults and validate the release."""
import ctypes
from ctypes import wintypes
import json
import importlib
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import time
import urllib.request
import core

REPORT=core.ROOT/'verification-final-context.json'
STATUS=core.ROOT/'logs/maximum-context-status.json'
CANCEL=core.ROOT/'logs/context-test-cancelled'
result={'ok':False}

def save(phase):
    result['phase']=phase
    REPORT.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')

def models():
    settings=core.load_settings()
    req=urllib.request.Request('http://127.0.0.1:8081/v1/models',headers={
        'Authorization':'Bearer '+settings['api_key']})
    with urllib.request.urlopen(req,timeout=5) as response:
        return {item['id'] for item in json.load(response)['data']}

def private_clients_running():
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.OpenMutexW.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.LPCWSTR]
    kernel.OpenMutexW.restype=wintypes.HANDLE
    kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    handle=kernel.OpenMutexW(0x100000,False,'Local\\PersonalLocalCodexDesktop')
    if handle:
        kernel.CloseHandle(handle)
        return True
    path=str(core.ROOT/'engine/codex.exe').replace("'","''")
    command="@(Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -eq '"+path+"' }).Count"
    check=subprocess.run([r'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe',
        '-NoProfile','-NonInteractive','-Command',command],capture_output=True,
        timeout=30,creationflags=core.NO_WINDOW)
    return check.returncode!=0 or check.stdout.strip()!=b'0'

def wait_coordinator(pid):
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
    kernel.OpenProcess.restype=wintypes.HANDLE
    kernel.QueryFullProcessImageNameW.argtypes=[wintypes.HANDLE,wintypes.DWORD,wintypes.LPWSTR,ctypes.POINTER(wintypes.DWORD)]
    kernel.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD]
    kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    handle=kernel.OpenProcess(0x100000|0x1000,False,pid)
    if not handle:
        return
    try:
        buffer=ctypes.create_unicode_buffer(32768)
        length=wintypes.DWORD(len(buffer))
        assert kernel.QueryFullProcessImageNameW(handle,0,buffer,ctypes.byref(length))
        assert Path(buffer.value).resolve()==Path(sys.executable).resolve()
        while kernel.WaitForSingleObject(handle,30000)==258:
            if CANCEL.exists():
                raise RuntimeError('Benchmark cancelled; final settings were not applied')
    finally:
        kernel.CloseHandle(handle)

def finish():
    assert not CANCEL.exists(), 'Benchmark cancelled'
    state=json.loads(STATUS.read_text(encoding='utf-8'))
    assert state['phase']=='complete', 'Benchmark did not complete normally'
    core.stop_model()
    settings=core.load_settings()
    settings['model_contexts']=core.context_limits()
    result['local_token_rotated']=not private_clients_running()
    if result['local_token_rotated']:
        settings['api_key']=secrets.token_hex(24)
    core.prepare(settings)
    result['verified_contexts']=settings['model_contexts']
    save('validating_release')
    importlib.reload(importlib.import_module('update_context_report')).publish()
    for name in ('上下文极限测试报告.md','模型调研与使用说明.md'):
        shutil.copy2(core.ROOT/name,Path(__file__).parent/name)
    for command in ([sys.executable,str(Path(__file__).parent/'app.py'),'--smoke-test'],
                    [str(core.ROOT/'app/MyCodex/MyCodex.exe'),'--smoke-test']):
        check=subprocess.run(command,capture_output=True,timeout=120,creationflags=core.NO_WINDOW)
        assert check.returncode==0, 'Desktop UI verification failed'
    core.start_gateway()
    assert models()==set(core.MODELS), 'Adapter does not list both local models'
    catalog=json.loads((core.ROOT/'model-catalog.json').read_text(encoding='utf-8'))['models']
    assert {item['slug'] for item in catalog}==set(core.MODELS)
    for item in catalog:
        assert item['context_window']==settings['model_contexts'][item['slug']]
    result['desktop_and_catalog_verified']=True
    save('starting_desktop')
    name=core.selected_model(settings)
    core.start_model(name,settings['model_contexts'][name],wait=True)
    deadline=time.monotonic()+1250
    while not core.server_ready():
        assert not CANCEL.exists(), 'Final startup cancelled'
        assert time.monotonic()<deadline, 'Final desktop model did not start'
        time.sleep(1)
    props=core.api('/props')
    allocated=props['default_generation_settings']['n_ctx']
    context=settings['model_contexts'][name]
    assert Path(props['model_path'])==core.model_file(name)
    assert context-1<=allocated<context+256
    result['active_model']=name
    result['allocated_context']=allocated
    subprocess.Popen([str(core.ROOT/'app/MyCodex/MyCodex.exe')],creationflags=core.NO_WINDOW)
    result['ok']=True
    save('complete')

if __name__=='__main__':
    if '--preflight' in sys.argv:
        assert models()==set(core.MODELS)
        assert (core.ROOT/'app/MyCodex/MyCodex.exe').is_file()
        print(json.dumps({'adapter_lists_both_models':True,
            'private_clients_active':private_clients_running()}))
        raise SystemExit(0)
    try:
        save('awaiting_benchmark')
        wait_coordinator(int(sys.argv[1]))
        finish()
    except Exception as error:
        result['error']=str(error)
        save('failed')
        raise
