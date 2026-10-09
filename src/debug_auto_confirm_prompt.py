"""End-to-end diagnostic of Xiaomi's verified USB-install confirmation prompt."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
sys.path.insert(0,str(Path(__file__).parent))
import local_mcp_servers as local
work=Path(r'G:\LocalCodex-work\mycodex-repair-20261009\artifacts\android-mcp-test')
apk=work/'huihui-apk-push-probe.apk'
package='com.mycodex.huihuipushprobe'
label='Huihui MCP Acceptance Probe'
pre=work/'manual-confirm-before.png'
post=work/'manual-confirm-after.png'


def markers(xml):
    root=ET.fromstring(xml)
    nodes=list(root.iter('node'))
    texts=[str(n.attrib.get(k) or '').strip() for n in nodes for k in ('text','content-desc')]
    is_prompt=any(mark in text for mark in ('USB安装提示','通过USB安装','USB install','Install via USB') for text in texts)
    button=[]
    for node in nodes:
        text=str(node.attrib.get('text') or node.attrib.get('content-desc') or '').strip()
        bounds=re.fullmatch(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]',node.attrib.get('bounds',''))
        if text in ('继续安装','继续','Continue install','Install anyway') and node.attrib.get('clickable')=='true' and bounds:
            left,top,right,bottom=map(int,bounds.groups());button.append(((left+right)//2,(top+bottom)//2))
    return texts,is_prompt,button


def capture(path):
    result=subprocess.run([str(local.ADB),'-s',local.DEVICE,'exec-out','screencap','-p'],
        capture_output=True,timeout=20,creationflags=local.NO_WINDOW)
    if result.returncode or not result.stdout.startswith(b'\x89PNG\r\n\x1a\n'): raise RuntimeError('Bad PNG screenshot')
    path.write_bytes(result.stdout)


try:
    code,installed=local._adb('shell','pm','path',package)
    if code==0 and 'package:' in installed:
        code,output=local._adb('uninstall',package,timeout=60)
        if code or 'Success' not in output: raise RuntimeError('Could not reset the dedicated acceptance package')
    code,install=local._adb('install','-r',str(apk),timeout=120)
    if code or 'Success' not in install: raise RuntimeError(f'Install command failed: {install}')
    xml='';texts=[];is_prompt=False;buttons=[]
    for _ in range(4):
        xml=local._read_android_ui_xml()
        if xml: texts,is_prompt,buttons=markers(xml)
        if is_prompt: break
        time.sleep(.3)
    if not is_prompt: raise RuntimeError('Expected USB install dialog did not appear.')
    if label not in texts: raise RuntimeError('USB install prompt did not show the exact acceptance app label.')
    if len(buttons)!=1: raise RuntimeError(f'Expected one confirm button; got {buttons}')
    (work/'manual-confirm-before.xml').write_text(xml,encoding='utf-8')
    capture(pre)
    x,y=buttons[0]
    code,tap=local._adb('shell','input','tap',str(x),str(y),timeout=10)
    method='adb-shell'
    if code and 'INJECT_EVENTS' in tap:
        code,tap=local._adb('shell','su','-c',f'input tap {x} {y}',timeout=10)
        method='root-su'
    if code: raise RuntimeError('ADB tap failed: '+tap)
    time.sleep(.8)
    after_xml=local._read_android_ui_xml()
    after_texts,still_prompt,_=markers(after_xml) if after_xml else ([],False,[])
    capture(post)
    if still_prompt and label in after_texts: raise RuntimeError('Prompt remained after exact button tap.')
    code,path=local._adb('shell','pm','path',package)
    if code or 'package:' not in path: raise RuntimeError('Package manager did not report the test app installed after confirmation.')
    result={'ok':True,'dialog_seen':True,'app_label_matched':True,'confirm_button_bounds_center':[x,y],
            'dialog_dismissed_after_tap':True,'installed':True,'app_launched':False,
            'confirmation_method':method,
            'before_screenshot':str(pre),'after_screenshot':str(post),
            'prompt_nodes':[n for n in texts if any(word in n for word in ('USB','安装','继续','Huihui'))]}
finally:
    code,path=local._adb('shell','pm','path',package)
    if code==0 and 'package:' in path:
        cleanup_code,cleanup=local._adb('uninstall',package,timeout=60)
        if cleanup_code or 'Success' not in cleanup: raise RuntimeError('Dedicated probe cleanup failed.')
print(json.dumps(result,ensure_ascii=False))
