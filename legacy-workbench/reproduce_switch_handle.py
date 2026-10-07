"""Capture the actual windowed-process context-switch failure without a long input."""
import ctypes
from ctypes import wintypes
import json
import traceback
import core

report={'ok':False,'stages':[]}
path=core.ROOT/'reproduction-switch-handle.json'
def save(stage):
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.GetStdHandle.argtypes=[wintypes.DWORD]
    kernel.GetStdHandle.restype=wintypes.HANDLE
    report['stages'].append({'stage':stage,'console_cp':kernel.GetConsoleCP(),
        'standard_handles':[kernel.GetStdHandle(value & 0xffffffff) for value in (-10,-11,-12)]})
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
try:
    save('before_start')
    core.start_model(core.MODEL,20480,wait=True)
    save('20k_ready')
    core.start_model(core.MODEL,65536,wait=True)
    report['ok']=True
    save('64k_ready')
except Exception as error:
    report['error']=str(error)
    report['traceback']=traceback.format_exc()
    save('failed')
