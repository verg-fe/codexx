"""Exercise WaitFor through the configured Windows Desktop MCP without screenshots."""
from __future__ import annotations
import asyncio
import json
import os
from pathlib import Path
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

PYTHON=Path(r'G:\LocalCodex\tools\photoslop-mcp-venv\Scripts\python.exe')
SERVER=Path(r'D:\LocalCodex\tools\windows-mcp-venv\Scripts\windows-mcp.exe')
OUT=Path(r'G:\LocalCodex-work\mycodex-repair-20261009\artifacts\mcp-acceptance\windows-waitfor.json')

async def main():
    env=dict(os.environ,PYTHONUTF8='1',PYTHONIOENCODING='utf-8',WINDOWS_MCP_WATCHDOG='false',
             ANONYMIZED_TELEMETRY='false',POSTHOG_API_KEY='')
    params=StdioServerParameters(command=str(SERVER),args=['serve','--transport','stdio','--tools','WaitFor'],env=env)
    evidence={'server':'windows_desktop','operation':'WaitFor','window_name_supplied':True}
    async with stdio_client(params) as (reader,writer):
        async with ClientSession(reader,writer) as client:
            await client.initialize()
            tool=next(t for t in (await client.list_tools()).tools if t.name=='WaitFor')
            schema=getattr(tool,'inputSchema',getattr(tool,'input_schema',{})) or {}
            properties=schema.get('properties',{})
            evidence['schema_has_window_name']='window_name' in properties
            assert evidence['schema_has_window_name'], schema
            try:
                result=await client.call_tool('WaitFor',{
                    'condition':'active_window','window_name':'我的 Codex · 本地编程工作台 · v54',
                    'timeout':5.0,'interval':0.25
                })
                failed=bool(getattr(result,'is_error',getattr(result,'isError',False)))
                evidence['call_status']='window_not_active_or_timeout' if failed else 'passed'
            except Exception as exc:
                # Keep only the exception type; the upstream message may include the user's active window title.
                evidence['call_status']='tool_call_error'
                evidence['error_type']=type(exc).__name__
    evidence['completed']=True
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(evidence,ensure_ascii=False))

if __name__=='__main__': asyncio.run(main())
