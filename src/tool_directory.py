"""Index MCP schemas on disk and expose only the directory plus selected tools."""
import hashlib
import json
import re
import time
import uuid
from pathlib import Path

ROOT=Path(r'G:\LocalCodex\tool-catalogs')
TAGS={'android':'手机 安卓 点击 坐标 安装 apk 截图 图标','android_coordinates':'手机 安卓 点击 坐标 截图 图标','ida':'ida 反编译 静态 调试 连接 启动 打开 插件 端口','frida':'frida 动态 调试','voice':'配音 语音 wav 录音','shotcut':'视频 剪辑 裁剪 mp4','photoslop':'图片 照片 图像 抠图','blender':'建模 网格 渲染','freecad':'cad 零件 stl step','vmware':'虚拟机 vmware','web':'搜索 新闻 网页 来源','history':'历史 记忆 技能 草稿','model':'模型 显存 下载 激活 上下文','windows_desktop':'电脑 桌面 窗口 点击 截图 OCR 文件 命令 powershell','design_control':'设计 画布 元素 图片 图层','design_analysis':'设计 分析 颜色 字体 布局','scopeweaver_source':'scopeweaver 源码 搜索 阅读 文件','tool_directory':'工具 目录 搜索 schema'}
# These MCP servers form one practical workflow. Exposing their complete schemas
# together avoids changing the prompt's tool prefix as a task moves from finding
# a screen target to OCR, coordinate mapping, and clicking.
RELATED_GROUPS={
    'android':{'android','android_coordinates'},
    'android_coordinates':{'android','android_coordinates'},
    'ida':{'ida','frida'},
    'frida':{'ida','frida'},
    'design_control':{'design_control','design_analysis'},
    'design_analysis':{'design_control','design_analysis'},
}
SCHEMA=('tool_catalog_search','Search the MCP tool directory by task or category and return tool names and short descriptions; schemas for the selected service bundle are added to the next request.',{'type':'object','properties':{'request_key':{'type':'string'},'query':{'type':'string'},'limit':{'type':'integer','default':4}},'required':['request_key','query']})

def search(request_key,query,limit=4):
    if not re.fullmatch('[0-9a-f]{32}',str(request_key)):raise ValueError('Invalid request_key.')
    if not str(query).strip():raise ValueError('Search by tool/category/task keywords.')
    state=json.loads((ROOT/(request_key+'.json')).read_text(encoding='utf-8'))
    words=re.findall(r'[a-z0-9_-]+|[\u4e00-\u9fff]+',str(query).lower())
    for label,english in {'点击':'click','图标':'icon','控件':'ui','裁剪':'crop','安装':'install','配音':'voice','记忆':'history','搜索':'search'}.items():
        if label in str(query):words.append(english)
    ranked=[]
    query_lower=str(query).lower()
    ida_query=('ida' in query_lower or '反汇编' in query_lower or '反编译' in query_lower)
    ida_recovery_query=ida_query and any(term in query_lower for term in (
        'connect','connection','probe','start','launch','server','mcp','启动','连接','连通','可用','不可用','检查','探测','端口'))
    for tool in state['tools']:
        name=tool.get('name','').lower();hay=name+' '+str(tool.get('description','')).lower()
        for key,tags in TAGS.items():
            if key in name:hay+=' '+tags
        score=sum(5 if word in name else 1 for word in words if word in hay)
        score+=sum(1 for tags in TAGS.values() for tag in tags.split() if tag in str(query) and tag in hay)
        if ida_recovery_query and name.endswith('__start_ida'):
            score+=12
        if score:ranked.append((score,name,tool))
    ranked.sort(key=lambda row:(-row[0],row[1]))
    result_rows=ranked[:max(1,min(int(limit),12))]
    if ida_recovery_query:
        start_row=next((row for row in ranked if row[2].get('name','').endswith('__start_ida')),None)
        if start_row is not None and all(row[2].get('name')!=start_row[2].get('name') for row in result_rows):
            result_rows=result_rows[:max(0,len(result_rows)-1)]+[start_row]
    matches=[{'name':row[2].get('name',''),
              'description':' '.join(str(row[2].get('description','')).split())[:240]}
             for row in result_rows]
    note='Lookup only. The selected MCP service schemas and any linked workflow service schemas will be exposed together on the next model request to keep the tool set stable.'
    if ida_recovery_query:
        note+=' For an IDA connection-refused probe, start_ida is the recovery action; omit target_path for a connectivity-only blank session.'
    return {'request_key':request_key,'matches':matches,'matching_count':len(ranked),
            'note':note}

def _walk_json(value):
    """Yield structured JSON nested in tool output text or MCP content blocks."""
    if isinstance(value,dict):
        yield value
        for child in value.values():
            yield from _walk_json(child)
    elif isinstance(value,list):
        for child in value:
            yield from _walk_json(child)
    elif isinstance(value,str):
        # Codex wraps MCP output as e.g. "Wall time ...\nOutput:\n{...}".
        # Incremental Responses requests can contain only function_call_output,
        # while previous_response_id retains the original function_call.
        text=value.strip()
        if not text or len(text)>512_000:
            return
        marker=re.search(r'(?:^|\r?\n)Output:\s*\r?\n',text)
        candidates=[text[marker.end():].strip(),text] if marker else [text]
        decoder=json.JSONDecoder()
        for candidate in candidates:
            if not candidate:
                continue
            try:
                parsed=json.loads(candidate)
            except (ValueError,TypeError):
                try:
                    parsed,_=decoder.raw_decode(candidate)
                except (ValueError,TypeError):
                    continue
            if parsed != value:
                yield from _walk_json(parsed)
                return

def _selected_names(body,key):
    inputs=body.get('input',[])
    if not isinstance(inputs,list):
        return set()
    last_user=max((i for i,item in enumerate(inputs)
                   if isinstance(item,dict) and item.get('role')=='user' and
                   item.get('type') in ('message','input_message')),default=-1)
    current=inputs[last_user+1:]
    calls={item.get('call_id'):str(item.get('name','')) for item in current
           if isinstance(item,dict) and item.get('type')=='function_call' and item.get('call_id')}
    available={tool.get('name') for tool in body.get('tools',[]) if isinstance(tool,dict)}
    selected=set()
    for item in current:
        if not isinstance(item,dict) or item.get('type')!='function_call_output':
            continue
        # A previous_response_id continuation may send only function_call_output,
        # or may include earlier calls but omit this output's matching call.
        call_name=calls.get(item.get('call_id'))
        if call_name is not None and not call_name.endswith('__tool_catalog_search'):
            continue
        for result in _walk_json(item.get('output')):
            if result.get('request_key') != key or not isinstance(result.get('matches'),list):
                continue
            for match in result.get('matches',[]):
                if isinstance(match,dict) and isinstance(match.get('name'),str) and match['name'] in available:
                    selected.add(match['name'])
    return selected

def _thread_selection_file(body):
    match=re.search(r'Local history archive thread_id: ([0-9a-fA-F-]{36})',str(body.get('instructions','')))
    if not match:return None
    identity=match.group(1).lower()
    if not re.fullmatch(r'[0-9a-f-]{36}',identity):return None
    digest=hashlib.sha256(identity.encode()).hexdigest()
    directory=ROOT/'thread-selections'
    directory.mkdir(parents=True,exist_ok=True)
    return directory/(digest+'.json')

def _latest_user_text(body):
    inputs=body.get('input',[])
    if not isinstance(inputs,list):return ''
    last_user=max((i for i,item in enumerate(inputs)
                   if isinstance(item,dict) and item.get('role')=='user' and
                   item.get('type') in ('message','input_message')),default=-1)
    if last_user<0:return ''
    def collect(value):
        if isinstance(value,str):return value
        if isinstance(value,list):return '\n'.join(filter(None,(collect(part) for part in value)))
        if isinstance(value,dict):
            if isinstance(value.get('text'),str):return value['text']
            return '\n'.join(filter(None,(collect(part) for part in value.values())))
        return ''
    return collect(inputs[last_user].get('content',''))

def _carry_task_groups(body,selected_groups):
    path=_thread_selection_file(body)
    if path is None:return selected_groups
    if selected_groups:
        record={'groups':sorted(selected_groups),'updated_at':time.time()}
    else:
        text=_latest_user_text(body)
        continuation=bool(re.search(r'继续当前未完成目标|继续(?:任务|目标)?\s*$|\b(?:continue|resume)\b',text,re.I))
        record={}
        if continuation:
            try:
                saved=json.loads(path.read_text(encoding='utf-8'))
                if time.time()-float(saved.get('updated_at',0))<72*3600:
                    record=saved
            except (OSError,ValueError,TypeError):
                pass
        else:
            record={'groups':[],'updated_at':time.time()}
    if record:
        temporary=path.with_name(path.stem+'-'+uuid.uuid4().hex+'.tmp')
        temporary.write_text(json.dumps(record,ensure_ascii=False),encoding='utf-8')
        temporary.replace(path)
    return set(record.get('groups',()))

def _always_available(tool):
    name=str(tool.get('name',''))
    short=name.rsplit('__',1)[-1]
    return name.endswith('__tool_catalog_search') or (
        'local_history' in name.split('__') and short in ('skill_search','skill_read'))

def register_tools(body,filter_schemas=True):
    tools=body.get('tools',[])
    if not any(str(tool.get('name','')).endswith('__tool_catalog_search') for tool in tools if isinstance(tool,dict)):
        return {'tool_directory_active':False}
    raw=json.dumps(sorted(tools,key=lambda tool:tool.get('name','')),ensure_ascii=False,sort_keys=True)
    key=hashlib.sha256(raw.encode()).hexdigest()[:32]
    ROOT.mkdir(parents=True,exist_ok=True)
    target=ROOT/(key+'.json')
    temp=ROOT/(key+'-'+uuid.uuid4().hex+'.tmp')
    temp.write_text(json.dumps({'tools':tools},ensure_ascii=False),encoding='utf-8')
    temp.replace(target)
    groups={}
    for tool in tools:
        name=tool.get('name','')
        match=re.search(r'(?:^|__)mcp__([^_].*?)__',name)
        if match:groups[match[1]]=groups.get(match[1],0)+1
    ref=('[MCP tool index: request_key='+key+'. Categories: '+
         ', '.join(f'{group}({count})' for group,count in sorted(groups.items()))+
         '. Search tool_catalog_search before using an MCP tool. Search results list names; the full schema bundle for selected services and linked workflow services is exposed on the next request. Do not guess hidden tool names or parameters.]')
    inputs=body.setdefault('input',[])
    if key not in json.dumps(inputs,ensure_ascii=False):
        inputs.append({'role':'user','content':[{'type':'input_text','text':ref}]})
    selected=_selected_names(body,key)
    if filter_schemas:
        selected_groups=set()
        for name in selected:
            match=re.search(r'(?:^|__)mcp__([^_].*?)__',name)
            if match:selected_groups.add(match[1])
        selected_groups=_carry_task_groups(body,selected_groups)
        expanded_groups=set(selected_groups)
        for group in tuple(selected_groups):
            expanded_groups.update(RELATED_GROUPS.get(group,{group}))
        allowed=set(selected)
        for tool in tools:
            name=str(tool.get('name',''))
            match=re.search(r'(?:^|__)mcp__([^_].*?)__',name)
            if match and match[1] in expanded_groups:allowed.add(name)
        # This directory filters MCP schemas only. Keep Codex-native tools
        # (exec_command, apply_patch, and other built-ins) visible at all times;
        # otherwise the model can repeatedly search for a built-in tool that
        # the gateway itself has hidden from the request.
        filtered=[tool for tool in tools if (
            _always_available(tool) or
            not re.search(r'(?:^|__)mcp__([^_].*?)__',str(tool.get('name',''))) or
            tool.get('name') in allowed)]
        # Preserve compatibility if an upstream tool catalog is malformed.
        if not any(str(tool.get('name','')).endswith('__tool_catalog_search') for tool in filtered):
            filtered=tools
        body['tools']=filtered
    else:
        filtered=tools
    return {'tool_directory_active':True,'request_key':key,
            'tools_before_directory':len(tools),'tools_after_directory':len(filtered),
            'selected_tool_names':sorted(selected),
            'selected_tool_groups':sorted(selected_groups) if filter_schemas else [],
            'expanded_tool_groups':sorted(expanded_groups) if filter_schemas else []}
