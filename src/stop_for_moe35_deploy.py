"""Honor the user's explicit stop before a private 150K backend probe."""
import ctypes
from ctypes import wintypes
from datetime import datetime
import json
from pathlib import Path
import subprocess
import sys
import time
import core
from verify_kv20 import native_state

def main():
    context_k=int(sys.argv[1]) if len(sys.argv)>1 else 150
    assert 8<=context_k<=256,'Private test context must be between 8K and 256K'
    root=core.ROOT;directory=root/'verification-project/moe35-deploy';directory.mkdir(parents=True,exist_ok=True)
    route=json.loads((root/'request-routing.json').read_text())
    thread=route['thread_id']
    native=next((root/'codex-home/sessions').rglob('*'+thread+'.jsonl'))
    turn,terminal,_=native_state(native)
    data={'authorized_by_user':True,'request':'暂停任务，从70K降低MoE4All窗口直到短生成可用后恢复对话','thread_id':thread,
        'turn_id':turn,'native_file':str(native),'settings':core.load_settings(),'active_model':core.active_model(),
        'native_was_terminal':terminal,'time':datetime.now().astimezone().isoformat()}
    (directory/'before.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    (directory/'settings-before.json').write_bytes((root/'settings.json').read_bytes())
    query="Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'MyCodex.exe' -and $_.ExecutablePath -like 'D:\\LocalCodex\\app\\*\\MyCodex.exe' -and $_.CommandLine -notmatch '--gateway|--history-server|--signal-model-console|--verify-' } | Select-Object ProcessId,ExecutablePath | ConvertTo-Json -Compress"
    result=subprocess.run(['powershell.exe','-NoProfile','-Command',query],capture_output=True,creationflags=core.NO_WINDOW,check=True)
    rows=json.loads(result.stdout.decode('utf-8-sig'))
    if not isinstance(rows,list):rows=[rows]
    assert len(rows)==1,'Find the one active owned desktop before closing it'
    pid=rows[0]['ProcessId'];data['gui_pid']=pid;data['gui_executable']=rows[0]['ExecutablePath']
    user=ctypes.WinDLL('user32',use_last_error=True)
    callback_type=ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)
    user.EnumWindows.argtypes=[callback_type,wintypes.LPARAM]
    user.GetWindowThreadProcessId.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.DWORD)]
    user.GetWindowTextW.argtypes=[wintypes.HWND,wintypes.LPWSTR,ctypes.c_int]
    user.PostMessageW.argtypes=[wintypes.HWND,wintypes.UINT,wintypes.WPARAM,wintypes.LPARAM]
    user.IsWindowVisible.argtypes=[wintypes.HWND]
    def windows():
        found=[]
        @callback_type
        def enum(hwnd,_):
            owner=wintypes.DWORD();user.GetWindowThreadProcessId(hwnd,ctypes.byref(owner))
            if owner.value==pid and user.IsWindowVisible(hwnd):
                buf=ctypes.create_unicode_buffer(512);user.GetWindowTextW(hwnd,buf,512)
                found.append((hwnd,buf.value))
            return True
        user.EnumWindows(enum,0);return found
    mains=[w for w in windows() if w[1].startswith('我的 Codex')]
    assert len(mains)==1,'The owned desktop main window is unavailable'
    user.PostMessageW(mains[0][0],0x0010,0,0)
    until=time.monotonic()+50;accepted=False
    from profiles26_guard import process_alive
    while time.monotonic()<until and process_alive(pid):
        for hwnd,title in windows():
            if title=='任务还在运行' and not accepted:
                # This exact stop dialog is approved by the human's reply above.
                user.PostMessageW(hwnd,0x0111,6,0);accepted=True
        time.sleep(.2)
    assert not process_alive(pid),'The native task must finish interruption before model testing'
    latest,ended,_=native_state(native)
    assert latest==turn and ended,'The original native turn was not confirmed terminal'
    data.update(native_terminal=True,gui_exited=True,stop_confirmation_accepted=accepted,
                native_file_mtime_ns=native.stat().st_mtime_ns)
    (directory/'before.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:data[k] for k in ('thread_id','turn_id','native_terminal','gui_exited')},ensure_ascii=False),flush=True)

if __name__=='__main__':main()
