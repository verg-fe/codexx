"""Complete the immediate model move after copy, then reopen the 20K desktop."""
import ctypes
from ctypes import wintypes
import json
from pathlib import Path
import subprocess
import sys
import core

REPORT=core.ROOT/'model-migration-finish.json'
state={'ok':False,'context_tokens':20480}

def save(phase):
    state['phase']=phase
    REPORT.write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf-8')

def wait_copy(pid):
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
    kernel.OpenProcess.restype=wintypes.HANDLE
    kernel.QueryFullProcessImageNameW.argtypes=[wintypes.HANDLE,wintypes.DWORD,wintypes.LPWSTR,ctypes.POINTER(wintypes.DWORD)]
    kernel.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD]
    kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    handle=kernel.OpenProcess(0x100000|0x1000,False,pid)
    if not handle:
        raise RuntimeError('Copy process not found')
    try:
        name=ctypes.create_unicode_buffer(32768)
        length=wintypes.DWORD(len(name))
        assert kernel.QueryFullProcessImageNameW(handle,0,name,ctypes.byref(length))
        assert Path(name.value).resolve()==Path(sys.executable).resolve()
        while kernel.WaitForSingleObject(handle,30000)==258:
            pass
    finally:
        kernel.CloseHandle(handle)

try:
    state['copy_pid']=int(sys.argv[1])
    save('waiting_for_copy')
    wait_copy(state['copy_pid'])
    migration=json.loads((core.ROOT/'model-migration.json').read_text(encoding='utf-8'))
    assert migration['ok'] and migration['phase']=='files_verified'
    save('configuring_g_paths')
    configuration=subprocess.run([sys.executable,str(Path(__file__).parent/'configure_g_models.py')],
        capture_output=True,timeout=60,creationflags=core.NO_WINDOW)
    assert configuration.returncode==0, configuration.stderr.decode(errors='replace')
    save('loading_20k_model_from_g')
    settings=core.load_settings()
    name=core.selected_model(settings)
    assert all(core.context_for(settings,model)==20480 for model in core.MODELS)
    core.start_model(name,20480,wait=True)
    props=core.api('/props')
    assert Path(props['model_path'])==core.model_file(name)
    assert core.model_file(name).parent==Path(r'G:\LocalCodex\models')
    assert props['default_generation_settings']['n_ctx']==20480
    state['active_model']=name
    state['actual_model_path']=props['model_path']
    save('removing_verified_d_copies')
    cleanup=subprocess.run([r'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe',
        '-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',
        str(Path(__file__).parent/'complete_model_move.ps1')],capture_output=True,
        timeout=120,creationflags=core.NO_WINDOW)
    assert cleanup.returncode==0, cleanup.stderr.decode(errors='replace')
    verification=json.loads((core.ROOT/'verification-20k-settings.json').read_text(encoding='utf-8'))
    verification['runtime_applied']=True
    verification['active_model']=name
    verification['model_directory']=str(core.MODEL_DIRECTORY)
    (core.ROOT/'verification-20k-settings.json').write_text(json.dumps(verification,indent=2),encoding='utf-8')
    desktop=subprocess.Popen([str(core.ROOT/'app/MyCodex/MyCodex.exe')],creationflags=core.NO_WINDOW)
    state['desktop_pid']=desktop.pid
    state['ok']=True
    save('complete')
except Exception as error:
    state['error']=str(error)
    save('failed')
    raise
