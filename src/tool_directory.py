"""Static MCP tool directory; the gateway preserves all advertised tool schemas."""
import hashlib
import json
import re
import uuid
from pathlib import Path

ROOT=Path(r'G:\LocalCodex\tool-catalogs')
TAGS={'android':'手机 安卓 点击 坐标 安装 apk 截图 图标','ida':'ida 反编译 静态 调试','frida':'frida 动态 调试','voice':'配音 语音 wav 录音','shotcut':'视频 剪辑 裁剪 mp4','photoslop':'图片 照片 图像 抠图','blender':'建模 网格 渲染','freecad':'cad 零件 stl step','vmware':'虚拟机 vmware','web':'搜索 新闻 网页 来源','history':'历史 记忆 技能 草稿','model':'模型 显存 下载 激活 上下文'}
SCHEMA=('tool_catalog_search','Search the MCP tool directory by task or category and return original names, descriptions, and schemas.',{'type':'object','properties':{'request_key':{'type':'string'},'query':{'type':'string'},'limit':{'type':'integer','default':6}},'required':['request_key','query']})

def search(request_key,query,limit=6):
    if not re.fullmatch('[0-9a-f]{32}',str(request_key)):raise ValueError('Invalid request_key.')
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
        score+=sum(1 for tags in TAGS.values() for tag in tags.split() if tag in str(query) and tag in hay)
        if score:ranked.append((score,name,tool))
    ranked.sort(key=lambda row:(-row[0],row[1]))
    matches=[row[2] for row in ranked[:max(1,min(int(limit),16))]]
    return {'request_key':request_key,'matches':matches,'matching_count':len(ranked),'note':'These are lookup results only. All original MCP tools are already available; search does not enable, disable, or execute a tool.'}

def register_tools(body):
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
    ref='[MCP tool directory: request_key='+key+'. Available categories: '+', '.join(f'{group}({count})' for group,count in sorted(groups.items()))+'. Search with tool_catalog_search for exact names and parameters. All original MCP tools remain available.]'
    body.setdefault('input',[]).append({'role':'user','content':[{'type':'input_text','text':ref}]})
    return {'tool_directory_active':True,'tools_before_directory':len(tools),'tools_after_directory':len(tools)}