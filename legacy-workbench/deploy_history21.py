"""Install only when native tasks are terminal; serialize against model switches."""
import json
from pathlib import Path
import subprocess
import core
from verify_kv20 import guard

def main():
    report=core.ROOT/'deployment-history21.json'
    if report.exists() and json.loads(report.read_text(encoding='utf-8-sig')).get('installed'):
        print(json.dumps({'installed':True,'already_installed':True}));return
    safe=guard()
    if not safe['safe']:
        print(json.dumps({'installed':False,'waiting':True,'guard':safe}));return
    with core.model_lock():
        safe=guard()
        if not safe['safe']:
            print(json.dumps({'installed':False,'waiting':True,'guard':safe}));return
        subprocess.run(['powershell','-NoProfile','-ExecutionPolicy','Bypass','-File',str(Path(__file__).with_suffix('.ps1'))],
            cwd=Path(__file__).parent,check=True,creationflags=core.NO_WINDOW)

if __name__=='__main__':main()
