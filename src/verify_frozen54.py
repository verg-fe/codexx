import asyncio
import json
import os
from pathlib import Path
import sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT=Path(r'D:\LocalCodex\staging\release54-verification\frozen')
ROOT.mkdir(parents=True,exist_ok=True)
EXE=Path(__file__).parent/'dist/MyCodex/MyCodex.exe'
RESULT=[]

async def check(service, tool, args=None):
    env=dict(os.environ,LOCAL_CODEX_ROOT=str(ROOT),LOCAL_CODEX_MODELS=r'G:\LocalCodex\models',PYTHONUTF8='1')
    params=StdioServerParameters(command=str(EXE),args=['--local-mcp-server',service],env=env)
    with (ROOT/(service+'.log')).open('w',encoding='utf-8') as log:
        async with stdio_client(params,errlog=log) as (r,w):
            async with ClientSession(r,w) as session:
                init=await session.initialize()
                listing=await session.list_tools()
                result=await session.call_tool(tool,args or {})
                if result.isError:raise RuntimeError(str(result.content))
                row={'service':service,'version':init.serverInfo.version,'tool_count':len(listing.tools),
                     'tool':tool,'result':result.structuredContent or str(result.content)}
                if service=='voice':
                    voice=await session.call_tool('voice_synthesize',{'text':'中文配音工具已经接通，可以生成音频。'})
                    job=voice.structuredContent
                    if not job:raise RuntimeError('missing voice job')
                    for _ in range(100):
                        await asyncio.sleep(.1)
                        response=await session.call_tool('voice_job_status',{'job_id':job['id']})
                        state=response.structuredContent
                        if state['status'] in ('failed','completed','cancelled'):break
                    if state['status']!='completed':raise RuntimeError(str(state))
                    row['voice_output']=state
                RESULT.append(row)
                print(service,'OK',row['tool_count'],flush=True)

async def main():
    for service,tool in (('model-manager','model_list'),('photoshop','photoshop_status'),
                         ('premiere','premiere_status'),('voice','voice_list')):
        await asyncio.wait_for(check(service,tool),timeout=45)
    (ROOT/'result.json').write_text(json.dumps(RESULT,ensure_ascii=False,indent=2),encoding='utf-8')

if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    asyncio.run(main())
