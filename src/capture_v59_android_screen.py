"""Capture the authorized Android device screen through the packaged v59 MCP."""
import json
import os
from pathlib import Path
import subprocess

exe=Path(os.environ['LOCAL_CODEX_V59_EXE'])
destination=Path(r'G:\LocalCodex-work\mycodex-repair-20261009\artifacts\android-mcp-test\phone-after-acceptance.png')
requests=[
    {'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2024-11-05'}},
    {'jsonrpc':'2.0','id':2,'method':'tools/call','params':{'name':'android_screenshot','arguments':{'destination':str(destination)}}},
]
proc=subprocess.Popen([str(exe),'--local-mcp-server','android'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,text=True,encoding='utf-8',env=os.environ.copy())
stdout,stderr=proc.communicate(''.join(json.dumps(item)+'\n' for item in requests),timeout=60)
if proc.returncode:
    raise RuntimeError(stderr[:1000])
replies={item['id']:item for item in (json.loads(line) for line in stdout.splitlines() if line.strip())}
result=replies[2]['result']
if result.get('isError'):
    raise RuntimeError(result['content'][0]['text'])
if not destination.is_file() or not destination.read_bytes().startswith(b'\x89PNG\r\n\x1a\n'):
    raise AssertionError('Screenshot MCP did not produce a valid PNG.')
report={'ok':True,'path':str(destination),'bytes':destination.stat().st_size,'png_signature_valid':True}
(destination.parent/'phone-screenshot-evidence.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False))
