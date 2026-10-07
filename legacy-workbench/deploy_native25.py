"""Serialize the no-XML upgrade against all users of the shared model."""
from pathlib import Path
import subprocess
import sys
import core

if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8',errors='replace')
    with core.model_lock():
        shell=Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/native/powershell/pwsh.exe'
        result=subprocess.run([str(shell),'-NoProfile','-ExecutionPolicy','Bypass','-File',str(Path(__file__).with_suffix('.ps1'))],
            creationflags=core.NO_WINDOW,capture_output=True,text=True,encoding='utf-8',errors='replace')
        print(result.stdout,end='')
        if result.stderr:print(result.stderr,end='')
    raise SystemExit(result.returncode)
