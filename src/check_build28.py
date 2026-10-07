"""Private packaged UI and native MCP checks; no daily model requests."""
import hashlib
import json
import subprocess
import sys
from pathlib import Path
import core
from verify_build23 import main as verify_ui

def main():
    exe=core.ROOT/'staging/emotion-mix-28-ready/MyCodex/MyCodex.exe'
    modes=('native','angry','desperate','obedient','open_xml','custom','legacy');reports={}
    for mode in modes:
        name='verification-build28-'+mode+'.json';verify_ui(exe,name,directive_mode=mode)
        reports[mode]=json.loads((core.ROOT/name).read_text(encoding='utf-8'))
    result=subprocess.run([sys.executable,'-X','utf8','verify_draft_native28.py','--frozen',str(exe)],
        creationflags=core.NO_WINDOW,cwd=Path(__file__).parent,timeout=90)
    assert result.returncode==0
    report={'ok':all(r['ok'] for r in reports.values()),'modes':list(modes),'private_frozen_ui':True,
        'frozen_native_mcp':True,'model_requests':0,'slider_range':[-.5,.5],'slider_step':.0001,
        'independent_channels':2,'joyful_sad_choices':True,
        'executable_sha256':hashlib.sha256(exe.read_bytes()).hexdigest()}
    (core.ROOT/'verification-build28.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report),flush=True)
if __name__=='__main__':main()
