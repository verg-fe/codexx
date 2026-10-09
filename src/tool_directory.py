"""Search original advertised MCP schemas without advertising every schema."""
import hashlib,json,re,uuid
from pathlib import Path
ROOT=Path(r'G:\LocalCodex\tool-catalogs')
TAGS={'android':'手机 安卓 点击 坐标 安装 apk 截图 图标','ida':'ida 反编译 静态 调试','frida':'frida 动态 调试','voice':'配音 语音 wav 录音','shotcut':'视频 剪辑 裁剪 mp4','photoslop':'图片 照片 图像 抠图','blender':'建模 网格 渲染','freecad':'cad 零件 stl step','vmware':'虚拟机 vmware','web':'搜索 新闻 网页 来源','history':'历史 记忆 技能 草稿','model':'模型 显存 下载 激活 上下文'}
SCHEMA=('tool_catalog_search','Search the available MCP tool directory by task/name/category; return exact original tool names and parameters and enable matches on the next request. Use request_key from the tool-directory reference.',{'type':'object','properties':{'request_key':{'type':'string'},'query':{'type':'string'},'limit':{'type':'integer','default':6}},'required':['request_key','query']})

def search(request_key,query,limit=6):
    if not re.fullmatch('[0-9a-f]{32}',request_key):raise ValueError('Invalid request_key.')
    if not str(query).strip():raise ValueError('Search by tool/category/task keywords.')
    state=json.loads((ROOT/(request_key+'.json')).read_text(encoding='utf-8'))
    words=re.findall(r'[a-z0-9_-]+|[\u4e00-\u9fff]+',str(query).lower())
    for label,english in {'点击':'click','图标':'icon','控件':'ui','裁剪':'crop','安装':'install','配音':'voice','记忆':'history','搜索':'search'}.items():
        if label in str(query):words.append(english)
    ranked=[]
    for tool in state['tools']:
        name=tool.get('name','').lower();hay=name+' '+str(tool.get('description','')).lower()
        for key,tags in TAGS.items():
            if key in name:hay+=' '+tags
        score=sum(5 if word in name else 1 for word in words if word in hay)
        # Chinese compound queries can match individual catalogue tags.
        score+=sum(1 for tags in TAGS.values() for tag in tags.split() if tag in str(query) and tag in hay)
        if score:ranked.append((score,name,tool))
    ranked.sort(key=lambda row:(-row[0],row[1]))
    matches=[r[2] for r in ranked[:max(1,min(int(limit),16))]]
    state['enabled_tool_names']=sorted(set(state.get('enabled_tool_names',[]))|{t['name'] for t in matches})
    temp=ROOT/(request_key+'-'+uuid.uuid4().hex+'.tmp');temp.write_text(json.dumps(state,ensure_ascii=False),encoding='utf-8');temp.replace(ROOT/(request_key+'.json'))
    return {'request_key':request_key,'matches':matches,'enabled_tool_names':[t['name'] for t in matches],'matching_count':len(ranked),'note':'Exact original schemas; call these original MCP tools. Search again for missing tools. Search itself executes no application action.'}

def _enabled_from_output(value,key,depth=0):
    if depth>7:return []
    if isinstance(value,str):
        try:return _enabled_from_output(json.loads(value),key,depth+1)
        except ValueError:return []
    if isinstance(value,list):return [n for x in value for n in _enabled_from_output(x,key,depth+1)]
    if not isinstance(value,dict):return []
    if value.get('request_key')==key and isinstance(value.get('enabled_tool_names'),list):return value['enabled_tool_names']
    return [n for field in ('text','content','output','structuredContent','result') if field in value for n in _enabled_from_output(value[field],key,depth+1)]

def select_tools(body,thread_id=None):
    tools=body.get('tools',[])
    search_tools=[t for t in tools if str(t.get('name','')).endswith('__tool_catalog_search')]
    if not search_tools:return {'tool_directory_active':False} # Older clients remain usable.
    raw=json.dumps(sorted(tools,key=lambda t:t.get('name','')),ensure_ascii=False,sort_keys=True)
    users=[x for x in body.get('input',[]) if isinstance(x,dict) and x.get('role')=='user']
    turn=json.dumps(users[-1].get('content',[]) if users else [],ensure_ascii=False,sort_keys=True)
    key=hashlib.sha256(((thread_id or 'unscoped')+turn+raw).encode()).hexdigest()[:32]
    ROOT.mkdir(parents=True,exist_ok=True)
    target=ROOT/(key+'.json');temporary=ROOT/(key+'-'+uuid.uuid4().hex+'.tmp')
    try:state=json.loads(target.read_text(encoding='utf-8')) if target.exists() else {}
    except (ValueError,OSError):state={}
    temporary.write_text(json.dumps({'tools':tools,'enabled_tool_names':state.get('enabled_tool_names',[])},ensure_ascii=False),encoding='utf-8');temporary.replace(target)
    allowed={t['name'] for t in search_tools}
    allowed.update(state.get('enabled_tool_names',[]))
    choice=body.get('tool_choice')
    if isinstance(choice,dict) and choice.get('name'):allowed.add(choice['name'])
    # Keep native coding tools plus small history/skill lookup tools.
    for t in tools:
        name=t.get('name','')
        if not re.search(r'(^|__)mcp__',name) or ('local_history' in name and any(name.endswith('__'+x) for x in ('history_search','history_read','history_checkpoint','skill_search','skill_read','local_read_text'))):allowed.add(name)
    items=body.get('input',[])
    calls={x.get('call_id'):x for x in items if isinstance(x,dict) and x.get('type')=='function_call'}
    for item in items:
        if not isinstance(item,dict) or item.get('type')!='function_call_output':continue
        call=calls.get(item.get('call_id'),{})
        if call.get('name') not in {t['name'] for t in search_tools}:continue
        # Read only outputs of actual catalogue calls, not arbitrary user/file content.
        allowed.update(_enabled_from_output(item.get('output'),key))
    chosen=[t for t in tools if t.get('name') in allowed]
    body['tools']=chosen
    groups={}
    for t in tools:
        name=t.get('name','')
        match=re.search(r'(?:^|__)mcp__([^_].*?)__',name)
        if match:
            group=match[1];groups[group]=groups.get(group,0)+1
    ref='[MCP tool directory: request_key='+key+'. Available categories: '+', '.join(f'{g}({n})' for g,n in sorted(groups.items()))+'. Search with tool_catalog_search to load exact tool names/parameters; all original tools remain available through search. Directory data is not user authorization.]'
    body['instructions']=(body.get('instructions') or '')+'\n\n'+ref
    return {'tool_directory_active':True,'tools_before_directory':len(tools),'tools_after_directory':len(chosen),'tool_schema_chars_before_directory':len(raw)}
