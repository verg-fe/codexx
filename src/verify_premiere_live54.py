"""Actual stdio MCP and Premiere host acceptance; never simulate the host."""
import asyncio
import json
from pathlib import Path
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(r'D:\LocalCodex\staging\release54-verification')
EXE = Path(r'D:\LocalCodex\app\MyCodex-media-mcp54\MyCodex.exe')

async def main():
    results = {}
    async with stdio_client(StdioServerParameters(command=str(EXE), args=['--local-mcp-server','premiere'])) as (r,w):
        async with ClientSession(r,w) as session:
            await session.initialize()
            results['tools'] = [t.name for t in (await session.list_tools()).tools]
            async def call(label, tool, args):
                result = await session.call_tool(tool, args)
                data = result.structuredContent or [v.model_dump() for v in result.content]
                results[label] = {'isError': result.isError, 'response': data}
                return result, data
            _, status = await call('status', 'premiere_status', {})
            invalid,_ = await call('missing_file', 'premiere_open', {'path':str(ROOT/'not-present-acceptance.prproj')})
            assert invalid.isError, 'Missing path must fail before host execution'
            empty,_ = await call('empty_script', 'premiere_execute_script', {'script':''})
            assert empty.isError, 'Empty script must fail'
            if isinstance(status,dict) and status.get('panel_connected'):
                info,_ = await call('project_read', 'premiere_document_info', {})
                assert not info.isError
                reply,_ = await call('host_roundtrip', 'premiere_execute_script',
                    {'script':'"PR54:" + app.version','timeout':10})
                assert not reply.isError
                error,_ = await call('host_error', 'premiere_execute_script',
                    {'script':'throw new Error("PR54 expected error")','timeout':10})
                assert error.isError
                results['host_verified'] = True
            else:
                disconnected,_ = await call('disconnected_host', 'premiere_document_info', {})
                assert disconnected.isError
                results['host_verified'] = False
                results['pending'] = 'Real Premiere panel connection and editing'
    ROOT.mkdir(exist_ok=True,parents=True)
    (ROOT/'premiere-live-result.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(results,ensure_ascii=False,indent=2))

if __name__ == '__main__': asyncio.run(main())
