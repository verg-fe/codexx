"""Stop only this verification script, then its owned inference process."""
import ctypes
from ctypes import wintypes
from pathlib import Path
import core

class Entry(ctypes.Structure):
    _fields_=[('size',wintypes.DWORD),('usage',wintypes.DWORD),('pid',wintypes.DWORD),
        ('heap',ctypes.c_size_t),('module',wintypes.DWORD),('threads',wintypes.DWORD),
        ('parent',wintypes.DWORD),('priority',wintypes.LONG),('flags',wintypes.DWORD),
        ('name',wintypes.WCHAR*260)]
class UnicodeString(ctypes.Structure):
    _fields_=[('length',wintypes.USHORT),('max_length',wintypes.USHORT),('buffer',ctypes.c_void_p)]
k=ctypes.WinDLL('kernel32',use_last_error=True)
n=ctypes.WinDLL('ntdll')
k.CreateToolhelp32Snapshot.restype=wintypes.HANDLE
k.OpenProcess.restype=wintypes.HANDLE
k.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
k.CloseHandle.argtypes=[wintypes.HANDLE]
k.Process32FirstW.argtypes=[wintypes.HANDLE,ctypes.POINTER(Entry)]
k.Process32NextW.argtypes=k.Process32FirstW.argtypes
k.QueryFullProcessImageNameW.argtypes=[wintypes.HANDLE,wintypes.DWORD,wintypes.LPWSTR,ctypes.POINTER(wintypes.DWORD)]
k.TerminateProcess.argtypes=[wintypes.HANDLE,wintypes.UINT]
k.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD]
n.NtQueryInformationProcess.argtypes=[wintypes.HANDLE,wintypes.ULONG,ctypes.c_void_p,wintypes.ULONG,ctypes.POINTER(wintypes.ULONG)]
snapshot=k.CreateToolhelp32Snapshot(2,0)
entry=Entry();entry.size=ctypes.sizeof(entry)
more=k.Process32FirstW(snapshot,ctypes.byref(entry))
try:
    while more:
        if entry.name.lower()=='python.exe':
            handle=k.OpenProcess(0x1000|0x100000|1,False,entry.pid)
            if handle:
                try:
                    path=ctypes.create_unicode_buffer(32768);size=wintypes.DWORD(len(path))
                    if k.QueryFullProcessImageNameW(handle,0,path,ctypes.byref(size)) and Path(path.value)==Path(r'C:\Python314\python.exe'):
                        length=wintypes.ULONG()
                        n.NtQueryInformationProcess(handle,60,None,0,ctypes.byref(length))
                        if 0<length.value<65536:
                            buf=ctypes.create_string_buffer(length.value)
                            if n.NtQueryInformationProcess(handle,60,buf,length,ctypes.byref(length))==0:
                                value=UnicodeString.from_buffer(buf)
                                command=ctypes.wstring_at(value.buffer,value.length//2)
                                if command.rstrip().endswith(' verify_model_picker.py'):
                                    print('Stopping verified UI test PID',entry.pid,flush=True)
                                    k.TerminateProcess(handle,1);k.WaitForSingleObject(handle,10000)
                finally:k.CloseHandle(handle)
        more=k.Process32NextW(snapshot,ctypes.byref(entry))
finally:k.CloseHandle(snapshot)
core.stop_model()
print('Verification process recovery complete',flush=True)
