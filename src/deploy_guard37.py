"""Activate the requested v37 update using only verified application processes."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import core

ROOT=core.ROOT
DESTINATION=ROOT/'app'/'MyCodex-guard37'

def main():
    stage=ROOT/'staging'/'guard37-ready'/'MyCodex'
    if not (stage/'MyCodex.exe').is_file():raise RuntimeError('Build is missing')
    backup=json.loads((ROOT/'backup-before-v37.json').read_text(encoding='utf-8'))
    if not Path(backup['path']).is_dir() or not backup.get('verified_sha256'):raise RuntimeError('Backup is missing')
    old=core.active_model()
    if old.get('pid') and not core.owned_process(old['pid']):raise RuntimeError('Model ownership cannot be confirmed')
    # The user authorized stopping the old looping task. Never touch other apps.
    if old.get('pid'):core.stop_model()
    shutil.copytree(stage,DESTINATION,dirs_exist_ok=True)
    desktop=Path(r'C:\Users\18213\Desktop\我的Codex.cmd')
    desktop.write_text('@echo off\nstart "" "'+str(DESTINATION/'MyCodex.exe')+'"\n',encoding='utf-8')
    with (ROOT/'logs'/'desktop37-startup.log').open('a',encoding='utf-8') as log:
        gui=subprocess.Popen([str(DESTINATION/'MyCodex.exe')],stdin=subprocess.DEVNULL,
            stdout=log,stderr=log,creationflags=core.NO_WINDOW)
    report=dict(installed=True,ui_pid=gui.pid,executable=str(DESTINATION/'MyCodex.exe'),
        executable_sha256=hashlib.sha256((DESTINATION/'MyCodex.exe').read_bytes()).hexdigest(),
        backup=backup['path'],app_version=core.APP_VERSION,started_at=time.time(),
        validation='Build completed; startup health and process evidence recorded separately. No regression test suite run.')
    (ROOT/'deployment-guard37.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))

if __name__=='__main__':main()
