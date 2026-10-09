"""Hold a Windows process handle while verifying identity and terminating it."""
import ctypes
from ctypes import wintypes
import os


def _kernel():
    if os.name != 'nt':
        raise OSError('This process identity implementation requires Windows')
    k = ctypes.WinDLL('kernel32', use_last_error=True)
    signatures = {
        'OpenProcess': ([wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE),
        'QueryFullProcessImageNameW': ([wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)], wintypes.BOOL),
        'GetProcessTimes': ([wintypes.HANDLE, *([ctypes.POINTER(wintypes.FILETIME)] * 4)], wintypes.BOOL),
        'WaitForSingleObject': ([wintypes.HANDLE, wintypes.DWORD], wintypes.DWORD),
        'TerminateProcess': ([wintypes.HANDLE, wintypes.UINT], wintypes.BOOL),
        'CloseHandle': ([wintypes.HANDLE], wintypes.BOOL),
    }
    for name, (args, result) in signatures.items():
        getattr(k, name).argtypes, getattr(k, name).restype = args, result
    return k


def _identity(k, handle, pid):
    if k.WaitForSingleObject(handle, 0) != 258:
        return None
    buf = ctypes.create_unicode_buffer(32768)
    size = wintypes.DWORD(len(buf))
    times = [wintypes.FILETIME() for _ in range(4)]
    if not k.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
        return None
    if not k.GetProcessTimes(handle, *(ctypes.byref(t) for t in times)):
        return None
    created = (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
    return {'pid': int(pid), 'executable': os.path.normcase(os.path.realpath(buf.value)), 'creation_filetime': created}


def process_identity(pid):
    k = _kernel()
    handle = k.OpenProcess(0x100000 | 0x1000, False, int(pid))
    if not handle:
        return None
    try:
        return _identity(k, handle, pid)
    finally:
        k.CloseHandle(handle)


def terminate_verified(expected):
    if not isinstance(expected, dict) or not all(expected.get(x) for x in ('pid', 'executable', 'creation_filetime')):
        return False
    k = _kernel()
    handle = k.OpenProcess(0x100000 | 0x1000 | 1, False, int(expected['pid']))
    if not handle:
        return False
    try:
        actual = _identity(k, handle, expected['pid'])
        if actual != expected:
            return False
        if not k.TerminateProcess(handle, 0):
            raise OSError(ctypes.get_last_error(), '无法结束已核验的受管进程')
        return k.WaitForSingleObject(handle, 10000) == 0
    finally:
        k.CloseHandle(handle)
