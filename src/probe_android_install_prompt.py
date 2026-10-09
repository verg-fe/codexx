"""Recreate the isolated probe install prompt and save its accessibility tree/screenshot on G."""
import json
import os
from pathlib import Path
import subprocess
import sys
sys.path.insert(0,str(Path(__file__).parent))
import local_mcp_servers as local
work=Path(r'G:\LocalCodex-work\mycodex-repair-20261009\artifacts\android-mcp-test')
apk=work/'huihui-apk-push-probe.apk'
package='com.mycodex.huihuipushprobe'
code,path=local._adb('shell','pm','path',package)
if code==0 and 'package:' in path:
    uninstall_code,uninstall=local._adb('uninstall',package,timeout=60)
    if uninstall_code or 'Success' not in uninstall:
        raise RuntimeError('Unable to remove only the prior dedicated acceptance probe: '+uninstall)
code,install=local._adb('install','-r',str(apk),timeout=120)
result=subprocess.run([str(local.ADB),'-s',local.DEVICE,'shell','uiautomator','dump','/sdcard/window.xml'],
                      capture_output=True,timeout=20,creationflags=local.NO_WINDOW)
code2,xml=local._adb('shell','cat','/sdcard/window.xml',timeout=10)
if result.returncode or code2:
    raise RuntimeError('Could not read live Android dialog hierarchy.')
(work/'install-prompt-probe.xml').write_text(xml,encoding='utf-8')
screen=subprocess.run([str(local.ADB),'-s',local.DEVICE,'exec-out','screencap','-p'],
                      capture_output=True,timeout=20,creationflags=local.NO_WINDOW)
if screen.returncode or not screen.stdout.startswith(b'\x89PNG\r\n\x1a\n'):
    raise RuntimeError('Could not capture live install prompt.')
(work/'install-prompt-probe.png').write_bytes(screen.stdout)
import xml.etree.ElementTree as ET
root=ET.fromstring(xml)
nodes=[]
for node in root.iter('node'):
    values={key:node.attrib.get(key,'') for key in ('class','text','content-desc','resource-id','clickable','bounds')}
    if any(values.values()): nodes.append(values)
report={'adb_install_exit_code':code,'adb_install_output':install,'nodes':nodes,
        'screenshot':str(work/'install-prompt-probe.png'),'xml':str(work/'install-prompt-probe.xml')}
(work/'install-prompt-probe.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'adb_install_exit_code':code,'adb_install_output':install,
    'relevant_nodes':[n for n in nodes if any(word.casefold() in (n['text']+n['content-desc']).casefold()
      for word in ('USB','安装','继续','拒绝','Huihui'))]},ensure_ascii=False))
