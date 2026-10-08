from pathlib import Path
from datetime import datetime
import json
import shutil
import subprocess
import sys
import time
import urllib.request

BASE=Path(__file__).resolve().parent
ROOT=Path('D:/LocalCodex')
sys.path.insert(0,str(BASE/'release52'))
import core

if any(s.get('is_processing') for s in core.api('/slots',timeout=3)):
    raise RuntimeError('Active inference: deployment deferred')
if json.loads((ROOT/'generation-status.json').read_text(encoding='utf-8')).get('phase')!='finished':
    raise RuntimeError('Active workbench: deployment deferred')
thread='01a117c9-8204-7352-8fde-2e7cf0cdf006'
from verify_kv20 import native_state
session=next((ROOT/'codex-home/sessions').rglob('*'+thread+'*.jsonl'))
if not native_state(session)[1]:raise RuntimeError('Native tools may be active')
target=ROOT/'app/MyCodex-runtime52'
if target.exists():raise RuntimeError('Preserve existing runtime52 destination')
backup=ROOT/'backups'/('runtime52-'+datetime.now().strftime('%Y%m%d-%H%M%S'))
backup.mkdir(parents=True)
launcher=Path('C:/Users/18213/Desktop/我的Codex.cmd')
resume=ROOT/'resume-after-moe32.json'
for p in (ROOT/'settings.json',launcher,resume):
    if p.exists():shutil.copy2(p,backup/p.name)
shutil.copytree(BASE/'release52/dist/MyCodex',target)
resume.write_text(json.dumps({'thread_id':thread,'authorized_by_user':True,'consumed':False,'prompt':'',
    'reason':'Client false-stop repair: restore session without starting a turn'},ensure_ascii=False,indent=2),encoding='utf-8')
launcher.write_bytes(('@echo off\r\nstart "" "C:\\Python314\\pythonw.exe" '
    '"C:\\Users\\18213\\Desktop\\codexx\\start_runtime52.py"\r\n').encode('utf-8'))
command="$p=Get-CimInstance Win32_Process | Where-Object {$_.Name -eq 'MyCodex.exe' -and $_.ExecutablePath -eq 'D:\\LocalCodex\\app\\MyCodex-tool-recovery51\\MyCodex.exe' -and $_.CommandLine -notmatch '--gateway|--history-server|--web-tools'}; $p | ForEach-Object {Stop-Process -Id $_.ProcessId}"
subprocess.run(['powershell.exe','-NoProfile','-Command',command],check=True,creationflags=core.NO_WINDOW)
process=subprocess.Popen([str(target/'MyCodex.exe'),'--no-auto-model','--resume-after-update'])
deadline=time.monotonic()+30
health=None
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
while time.monotonic()<deadline:
    if process.poll() is not None:raise RuntimeError('Updated GUI exited')
    try:
        request=urllib.request.Request('http://127.0.0.1:8081/health',headers={'Authorization':'Bearer '+core.load_settings()['api_key']})
        with opener.open(request,timeout=1) as response:health=json.load(response)
        if health.get('adapter_version')==core.ADAPTER_VERSION:break
    except (OSError,ValueError):pass
    time.sleep(.5)
else:raise RuntimeError('New adapter health not confirmed')
report={'version':52,'backup':str(backup),'app':str(target),'desktop_pid':process.pid,
    'adapter_version':health['adapter_version'],'thread':thread,'automatic_resume':False,
    'context':93000,'compact':87000,'kv_cache_type':'q4_0','vision_gpu_offload':False,
    'checks':['actual false-stop reasoning replay','bounded paragraph diagnostics','upstream terminal preservation',
              'malformed patch-arguments handling','consecutive recovery budget','lossless Unicode log batching',
              'packaged GUI stays alive and authenticated loopback health']}
(ROOT/'staging/runtime52-verified.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False))
