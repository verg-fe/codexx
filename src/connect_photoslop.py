"""Register the independently verified CPU editor without restarting inference."""
import json
from pathlib import Path
import shutil
import subprocess
import time
import tomllib

ROOT=Path(r'D:\LocalCodex')
PYTHON=Path(r'G:\LocalCodex\tools\photoslop-mcp-venv\Scripts\python.exe')
ADAPTER=ROOT/'tools/photoslop_huihui_mcp.py'
block=('\n[mcp_servers.photoslop]\ncommand = '+json.dumps(str(PYTHON))+
       '\nargs = '+json.dumps([str(ADAPTER),'--root',r'G:\LocalCodex\image-jobs'])+
       '\nstartup_timeout_sec = 30\ntool_timeout_sec = 300\nrequired = false\n'
       '\n[mcp_servers.photoslop.env]\nPYTHONUTF8 = "1"\nQT_QPA_PLATFORM = "offscreen"\n'
       'QT_OPENGL = "software"\nQT_QUICK_BACKEND = "software"\n'
       '\n[mcp_servers.photoslop.tools.edit_image]\napproval_mode = "approve"\n')
evidence=json.loads((ROOT/'staging/release54-verification/photoslop-live.json').read_text(encoding='utf-8'))
assert evidence.get('completed') is True
backup=ROOT/'backups'/('photoslop-connect-'+time.strftime('%Y%m%d-%H%M%S'))
backup.mkdir(parents=True)
changed=[]
for path in (ROOT/'codex-home').glob('*.toml'):
    content=path.read_text(encoding='utf-8-sig')
    if 'photoslop' in tomllib.loads(content).get('mcp_servers',{}):continue
    tomllib.loads(content+block)
    shutil.copy2(path,backup/path.name)
    temp=path.with_suffix('.toml.tmp')
    temp.write_text(content+block,encoding='utf-8');temp.replace(path)
    changed.append(str(path))
commit=subprocess.check_output(['git','-C',r'G:\LocalCodex\tools\image-editors\Photoslop','rev-parse','HEAD'],text=True).strip()
result={'source':'https://github.com/CryptoJones/Photoslop','commit':commit,'configured_files':changed,
        'backup':str(backup),'active_session_restarted':False,'huihui_model_call_verified':False,
        'actual_mcp_edit_verified':True,'image_root':r'G:\LocalCodex\image-jobs'}
(ROOT/'staging/release54-verification/photoslop-connection.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(result,ensure_ascii=False,indent=2))
