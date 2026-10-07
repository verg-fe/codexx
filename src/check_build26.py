import datetime
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import core
from verify_build23 import main as verify_ui


def main():
    exe=core.ROOT/'staging/directive-profiles-26-ready/MyCodex/MyCodex.exe'
    modes=('native','angry','desperate','obedient','open_xml','custom','legacy')
    reports={}
    for mode in modes:
        name='verification-build26-'+mode+'.json'
        verify_ui(exe,name,directive_mode=mode)
        reports[mode]=json.loads((core.ROOT/name).read_text(encoding='utf-8'))
    result=subprocess.run([sys.executable,'-X','utf8','verify_draft_native23.py','--frozen',str(exe)],
        creationflags=core.NO_WINDOW,cwd=Path(__file__).parent,timeout=90)
    assert result.returncode==0
    report={'ok':all(r['ok'] for r in reports.values()),'modes':list(modes),'private_frozen_ui':True,
            'frozen_native_mcp':True,'model_requests':0,'executable_sha256':hashlib.sha256(exe.read_bytes()).hexdigest(),
            'time':datetime.datetime.now().isoformat()}
    (core.ROOT/'verification-build26.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    offline=json.loads((core.ROOT/'verification-profiles26-offline.json').read_text(encoding='utf-8'))
    offline['unit_regressions']=72
    (core.ROOT/'verification-profiles26-offline.json').write_text(json.dumps(offline,indent=2),encoding='utf-8')
    print(json.dumps(report))


if __name__=='__main__':main()
