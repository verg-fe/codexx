"""Let the already running Jack benchmark finish, then skip its queued Huihui work."""
import ctypes
from ctypes import wintypes
import json
from pathlib import Path
import sys
import time
import core
import finalize_context_job as finalizer

def run(pid):
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
    kernel.OpenProcess.restype=wintypes.HANDLE
    kernel.QueryFullProcessImageNameW.argtypes=[wintypes.HANDLE,wintypes.DWORD,wintypes.LPWSTR,ctypes.POINTER(wintypes.DWORD)]
    kernel.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD]
    kernel.WaitForSingleObject.restype=wintypes.DWORD
    kernel.TerminateProcess.argtypes=[wintypes.HANDLE,wintypes.UINT]
    kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    handle=kernel.OpenProcess(0x100000|0x1000|1,False,pid)
    assert handle, 'Benchmark coordinator is not running'
    try:
        buffer=ctypes.create_unicode_buffer(32768)
        length=wintypes.DWORD(len(buffer))
        assert kernel.QueryFullProcessImageNameW(handle,0,buffer,ctypes.byref(length))
        assert Path(buffer.value).resolve()==Path(sys.executable).resolve()
        finalizer.result.update(coordinator_pid=pid,skipped_models=[core.HUIHUI_MODEL])
        finalizer.save('awaiting_jack_benchmark')
        while True:
            assert not finalizer.CANCEL.exists(), 'Benchmark cancelled'
            try:
                state=json.loads(finalizer.STATUS.read_text(encoding='utf-8'))
            except (OSError,ValueError):
                time.sleep(0.5)
                continue
            if state.get('model')==core.HUIHUI_MODEL and state.get('phase') in ('allocation','full_input'):
                # Jack results have been saved before entering this phase. Holding
                # the model lock prevents interruption between launch and PID save.
                with core.model_lock():
                    assert kernel.TerminateProcess(handle,0), 'Cannot stop queued benchmark'
                    assert kernel.WaitForSingleObject(handle,10000)==0, 'Coordinator did not exit'
                    core._stop_model()
                    state={'phase':'complete','verified':core.context_limits(),
                           'skipped_models':[core.HUIHUI_MODEL],'updated':time.time()}
                    temporary=finalizer.STATUS.with_suffix('.tmp')
                    temporary.write_text(json.dumps(state,ensure_ascii=False),encoding='utf-8')
                    temporary.replace(finalizer.STATUS)
                break
            if kernel.WaitForSingleObject(handle,500)==0:
                assert state.get('phase')=='complete', 'Jack benchmark exited before completing'
                break
        finalizer.finish()
    finally:
        kernel.CloseHandle(handle)

if __name__=='__main__':
    try:
        run(int(sys.argv[1]))
    except Exception as error:
        finalizer.result['error']=str(error)
        finalizer.save('failed')
        raise
