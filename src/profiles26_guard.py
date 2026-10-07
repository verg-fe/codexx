"""Serialize upgrades; accept only the exact user-cancelled migration turn."""
import ctypes
import json
import socket
from pathlib import Path
import core
from verify_kv20 import native_state, THREAD, TURN


def process_alive(pid):
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.OpenProcess.argtypes=[ctypes.c_ulong,ctypes.c_bool,ctypes.c_ulong]
    kernel.OpenProcess.restype=ctypes.c_void_p
    kernel.WaitForSingleObject.argtypes=[ctypes.c_void_p,ctypes.c_ulong]
    kernel.CloseHandle.argtypes=[ctypes.c_void_p]
    handle=kernel.OpenProcess(0x100000,False,int(pid))
    if not handle:return ctypes.get_last_error()==5
    try:return kernel.WaitForSingleObject(handle,0)==258
    finally:kernel.CloseHandle(handle)


def cancellation_covers(path,turn):
    receipt=core.ROOT/'cancelled-migration-20261003.json'
    try:data=json.loads(receipt.read_text(encoding='utf-8'))
    except (OSError,ValueError):return False
    return (data.get('authorized_by_user') is True and data.get('gui_and_engine_exited') is True
        and data.get('thread_id') in path.name and data.get('turn_id')==turn
        and not process_alive(data['gui_pid']) and not process_alive(data['engine_pid']))


def guard():
    paths=list((core.ROOT/'codex-home/sessions').rglob('*.jsonl'))
    observed=[p for p in paths if THREAD in p.name]
    if len(observed)!=1 or TURN not in native_state(observed[0])[2]:
        return {'safe':False,'reason':'Earlier observed task is not confirmed terminal'}
    roots=[core.ROOT/'codex-home/sessions',Path(r'C:\Users\18213\Desktop\codex-jack-cli\data\codex-home\sessions')]
    project=Path(r'C:\my_projects\my_codex')
    roots += [project/x for x in ('data/codex-home/sessions','codex-home/sessions','.codex/sessions')]
    for root in roots:
        if not root.exists():continue
        for path in sorted(root.rglob('*.jsonl'),key=lambda p:p.stat().st_mtime,reverse=True)[:8]:
            turn,terminal,_=native_state(path)
            if turn and not terminal and not cancellation_covers(path,turn):
                return {'safe':False,'reason':'Another native turn remains active','file':path.name}
    try:
        if any(s.get('is_processing') for s in core.api('/slots')):
            return {'safe':False,'reason':'Inference remains active'}
    except (OSError,ValueError):
        # A user-closed model has no slots endpoint. Confirm both process and port are absent.
        pid=core.active_model().get('pid')
        if pid and process_alive(pid):return {'safe':False,'reason':'Model process remains alive without a readable slots endpoint'}
        try:
            with socket.create_connection(('127.0.0.1',8080),timeout=3):
                return {'safe':False,'reason':'Model port has another listener'}
        except ConnectionRefusedError:
            return {'safe':True,'reason':'Native tasks ended or explicitly cancelled; model process is stopped'}
        except OSError as error:
            if getattr(error,'winerror',None)==10061 or error.errno in (10061,111):
                return {'safe':True,'reason':'Native tasks ended or explicitly cancelled; model process is stopped'}
            return {'safe':False,'reason':'Cannot confirm model port is closed'}
    return {'safe':True,'reason':'Native tasks terminal or explicitly cancelled; inference idle'}


if __name__=='__main__':print(json.dumps(guard(),ensure_ascii=False))
