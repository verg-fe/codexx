"""Exercise the v58 ScopeWeaver/VMware stdio MCPs over JSON-RPC and save evidence on G:."""
from __future__ import annotations
import json
import os
from pathlib import Path
import subprocess
import sys

SOURCE=Path(__file__).parent
PYTHON=Path(sys.executable)
WORK=Path(r'G:\LocalCodex-work\mycodex-repair-20261009')
PACKAGED_EXE=Path(os.environ['LOCAL_CODEX_V58_EXE']) if os.environ.get('LOCAL_CODEX_V58_EXE') else None
os.environ['LOCAL_CODEX_SCOPEWEAVER_SOURCE_ROOT']=r'G:\LocalCodex-work\scopeweaver-review-20261009'


def exercise(service, calls):
    requests=[{'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2024-11-05'}}]
    requests.append({'jsonrpc':'2.0','id':2,'method':'tools/list','params':{}})
    for index,(name,args) in enumerate(calls,3):
        requests.append({'jsonrpc':'2.0','id':index,'method':'tools/call','params':{'name':name,'arguments':args}})
    command=[str(PACKAGED_EXE),'--local-mcp-server',service] if PACKAGED_EXE else [str(PYTHON),str(SOURCE/'local_mcp_servers.py'),service]
    process=subprocess.Popen(command,cwd=SOURCE,
        stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8',
        env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'})
    payload=''.join(json.dumps(request,ensure_ascii=False)+'\n' for request in requests)
    stdout,stderr=process.communicate(payload,timeout=30)
    if process.returncode:
        raise RuntimeError(f'{service} exited {process.returncode}: {stderr[:1000]}')
    replies=[json.loads(line) for line in stdout.splitlines() if line.strip()]
    by_id={item['id']:item for item in replies}
    if len(by_id)!=len(requests):
        raise AssertionError(f'{service} returned {len(by_id)} responses for {len(requests)} requests')
    tools=by_id[2]['result']['tools']
    if any(not item.get('annotations',{}).get('readOnlyHint') for item in tools):
        raise AssertionError(f'{service} exposed a tool without a read-only annotation')
    result={'service':service,'tool_names':[item['name'] for item in tools],
            'calls':{(name if sum(1 for other,_ in calls if other==name)==1 else f'{name}_{index}'):
                     by_id[index]['result'] for index,(name,_) in enumerate(calls,3)}}
    return result


def exercise_bundled_skill():
    root=WORK/'tmp'/'v58-history-skill'
    root.mkdir(parents=True,exist_ok=True)
    command=([str(PACKAGED_EXE),'--history-server','--history-root',str(root)] if PACKAGED_EXE else
             [str(PYTHON),str(SOURCE/'history_memory.py'),'--history-server','--history-root',str(root)])
    requests=[
        {'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2024-11-05'}},
        {'jsonrpc':'2.0','id':2,'method':'tools/call','params':{'name':'skill_search','arguments':{'query':'ScopeWeaver','limit':10}}},
    ]
    proc=subprocess.Popen(command,cwd=SOURCE,
        stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8',
        env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'})
    stdout,stderr=proc.communicate(''.join(json.dumps(row)+'\n' for row in requests),timeout=20)
    if proc.returncode:
        raise RuntimeError('Packaged skill MCP failed: '+stderr[:1000])
    replies={row['id']:row for row in (json.loads(line) for line in stdout.splitlines() if line.strip())}
    search=replies[2]['result']
    if search.get('isError'):
        raise AssertionError('Bundled skill search returned an error: '+str(search))
    data=json.loads(search['content'][0]['text'])
    skill=next((row for row in data['skills'] if row['name']=='scopeweaver-source-review'),None)
    if not skill:
        raise AssertionError('ScopeWeaver skill was not discoverable from packaged app.')
    read_request={'jsonrpc':'2.0','id':3,'method':'tools/call','params':
                  {'name':'skill_read','arguments':{'name':'scopeweaver-source-review'}}}
    proc=subprocess.Popen(command,cwd=SOURCE,
        stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8',
        env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'})
    stdout,stderr=proc.communicate(json.dumps(read_request)+'\n',timeout=20)
    if proc.returncode:
        raise RuntimeError('Packaged skill read failed: '+stderr[:1000])
    replies=[json.loads(line) for line in stdout.splitlines() if line.strip()]
    result=next(row['result'] for row in replies if row['id']==3)
    if result.get('isError') or 'read-only' not in result['content'][0]['text']:
        raise AssertionError('Packaged ScopeWeaver skill content was not readable.')
    return {'search_found':True,'read_found':True,'reported_path':skill['path']}


def main():
    scopeweaver=exercise('scopeweaver-source',[
        ('scopeweaver_source_info',{}),
        ('scopeweaver_search_source',{'query':'AGPL-3.0','limit':3}),
        ('scopeweaver_read_source',{'relative_path':'README.md','max_chars':400}),
        ('scopeweaver_read_source',{'relative_path':'../README.md'}),
    ])
    vmware=exercise('vmware',[
        ('vmware_status',{}),
        ('vmware_list_running_vms',{}),
    ])
    if scopeweaver['calls']['scopeweaver_source_info']['isError'] or scopeweaver['calls']['scopeweaver_search_source']['isError'] or scopeweaver['calls']['scopeweaver_read_source_5']['isError']:
        summary={name:{'isError':row.get('isError'),'text':row.get('content',[{}])[0].get('text','')[:300]}
                 for name,row in scopeweaver['calls'].items()}
        raise AssertionError('ScopeWeaver source call failed: '+json.dumps(summary,ensure_ascii=True))
    if not scopeweaver['calls']['scopeweaver_source_info']['structuredContent']['history_preserved']:
        raise AssertionError('ScopeWeaver source metadata did not confirm preserved commit history')
    if not scopeweaver['calls']['scopeweaver_read_source_5']['structuredContent']['source_only']:
        raise AssertionError('ScopeWeaver source read did not declare source-only boundary')
    if not scopeweaver['calls']['scopeweaver_read_source_6']['isError']:
        raise AssertionError('ScopeWeaver path traversal was not rejected over MCP')
    if vmware['calls']['vmware_status']['isError'] or vmware['calls']['vmware_list_running_vms']['isError']:
        raise AssertionError('VMware status/read-only tool call failed')
    vm_status=vmware['calls']['vmware_status']['structuredContent']
    if not vm_status.get('installed') or vm_status.get('error') or not vm_status.get('vmware_size_bytes'):
        raise AssertionError('VMware status did not return a healthy metadata-only result: '+str(vm_status))
    bundled_skill=exercise_bundled_skill()
    evidence={'ok':True,'runtime':'packaged exe' if PACKAGED_EXE else 'source Python',
        'protocol':'JSON-RPC stdio initialize/list/call','scopeweaver':scopeweaver,'vmware':vmware,
        'bundled_skill':bundled_skill}
    out=WORK/'artifacts'/'verify-v58-mcp-live.json'
    out.write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'ok':True,'evidence':str(out),'scopeweaver_tools':scopeweaver['tool_names'],
        'scopeweaver_path_traversal_rejected':True,'vmware_tools':vmware['tool_names'],
        'bundled_skill_found':bundled_skill['search_found'] and bundled_skill['read_found'],
        'running_vm_count':vmware['calls']['vmware_list_running_vms']['structuredContent']['count']},ensure_ascii=False))


if __name__=='__main__':
    main()
