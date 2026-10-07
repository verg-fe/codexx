"""Publish the verified desktop fixes while retaining the user's chosen context."""
import json
from pathlib import Path
import shutil
import time
import core
from update_context_report import publish

report=json.loads((core.ROOT/'verification-visible-output.json').read_text(encoding='utf-8'))
assert report['ok'] is True, report.get('error',report.get('phase'))
settings=core.prepare()
assert settings['kv_cache_location']=='auto' and settings['cpu_offload'] is False
assert core.MAX_CONTEXT==256000 and core.GPU_CONTEXT_LIMIT==109568
publish()
workspace=Path(__file__).parent
for filename in ('上下文极限测试报告.md','模型调研与使用说明.md'):
    shutil.copy2(core.ROOT/filename,workspace/filename)
status_path=core.ROOT/'logs/maximum-context-status.json'
state=json.loads(status_path.read_text(encoding='utf-8'))
state['selected_contexts']=settings['model_contexts']
state['slider_max']=core.MAX_CONTEXT
state['settings_updated']=time.time()
state['settings_verification']='verification-visible-output.json'
status_path.write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf-8')
index_path=core.ROOT/'conversations/index.json'
sessions=json.loads(index_path.read_text(encoding='utf-8'))
for session in sessions:
    if session['id']==report['thread_id']:
        session['title']='[修复验证] 鹈鹕骑车 SVG'
index_path.write_text(json.dumps(sessions,ensure_ascii=False,indent=2),encoding='utf-8')
old_chat=core.ROOT/'conversations/01a0fdc3-4772-7c63-8075-fa1976cd9d07.txt'
note='◈ 会话诊断：上一轮耗时约6分38秒，全部13,306个输出token用于思考，耗尽20K上下文，没有正文或工具调用。现已安装思考上限、等待进度和空回复提示修复。'
if note not in old_chat.read_text(encoding='utf-8'):
    with old_chat.open('a',encoding='utf-8') as file:
        file.write('\n\n'+note+'\n')
source=Path(report['artifact'])
target=workspace/'pelican-cycling.svg'
if target.exists() and target.read_bytes()!=source.read_bytes():
    target=workspace/'pelican-cycling-verified.svg'
shutil.copy2(source,target)
print(json.dumps({'ok':True,'selected_context':settings['context'],'slider_max':core.MAX_CONTEXT,
    'gpu_context_limit':core.GPU_CONTEXT_LIMIT,'cache_mode':settings['kv_cache_location'],
    'svg':str(target)},ensure_ascii=False))
