"""Install v39 beside v38 and refresh the user's desktop entry."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import time
import core

def main():
    root=core.ROOT
    stage=root/'staging'/'debug39-ready'/'MyCodex'
    destination=root/'app'/'MyCodex-debug39'
    if not (stage/'MyCodex.exe').is_file():raise RuntimeError('Build is missing')
    if not (root/'backups'/'before-debug39'/'settings.json').is_file():raise RuntimeError('Settings backup is missing')
    if any(s.get('is_processing') for s in core.api('/slots')):raise RuntimeError('A model task is still running; preserve it')
    old=core.active_model()
    if old.get('pid'):
        if not core.owned_process(old['pid']):raise RuntimeError('Unconfirmed model process')
        core.stop_model()
    shutil.copytree(stage,destination,dirs_exist_ok=True)
    desktop=Path(r'C:\Users\18213\Desktop\我的Codex.cmd')
    desktop.write_text('@echo off\nstart "" "'+str(destination/'MyCodex.exe')+'"\n',encoding='utf-8')
    with (root/'logs'/'desktop39-startup.log').open('a',encoding='utf-8') as log:
        gui=subprocess.Popen([str(destination/'MyCodex.exe')],stdin=subprocess.DEVNULL,stdout=log,stderr=log,creationflags=core.NO_WINDOW)
    record=dict(installed=True,ui_pid=gui.pid,executable=str(destination/'MyCodex.exe'),
        executable_sha256=hashlib.sha256((destination/'MyCodex.exe').read_bytes()).hexdigest(),
        previous_program=str(root/'app'/'MyCodex-thinking38'),settings_backup=str(root/'backups'/'before-debug39'),
        version=core.APP_VERSION,started_at=time.time(),regression_tests_run=False)
    (root/'deployment-debug39.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(record,ensure_ascii=False))

if __name__=='__main__':main()

