"""Add the staged Premiere MCP without restarting an active workbench."""
import asyncio
import json
from datetime import datetime
from pathlib import Path
import shutil
import tomllib
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(r'D:\LocalCodex')
EXE = ROOT / 'app/MyCodex-media-mcp54/MyCodex.exe'

async def main():
    params = StdioServerParameters(command=str(EXE), args=['--local-mcp-server', 'premiere'])
    async with stdio_client(params) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            initialized = await session.initialize()
            listing = await session.list_tools()
            status = await session.call_tool('premiere_status', {})
            if status.isError:
                raise RuntimeError('Premiere MCP status failed')
            evidence = {'version': initialized.serverInfo.version,
                        'tools': [tool.name for tool in listing.tools],
                        'status': status.structuredContent or [part.model_dump() for part in status.content]}
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    backups = ROOT / 'backups' / ('premiere-mcp54-' + stamp)
    backups.mkdir(parents=True)
    block = ('\n[mcp_servers.premiere]\ncommand = ' + json.dumps(str(EXE)) +
             '\nargs = ["--local-mcp-server", "premiere"]\nstartup_timeout_sec = 20\n'
             'tool_timeout_sec = 300\nrequired = false\n')
    for suffix in ('open', 'execute_script'):
        block += f'\n[mcp_servers.premiere.tools.premiere_{suffix}]\napproval_mode = "approve"\n'
    changed = []
    for path in (ROOT / 'codex-home').glob('*.toml'):
        content = path.read_text(encoding='utf-8-sig')
        parsed = tomllib.loads(content)
        if 'premiere' in parsed.get('mcp_servers', {}):
            continue
        updated = content + block
        tomllib.loads(updated)
        shutil.copy2(path, backups / path.name)
        temporary = path.with_suffix('.toml.tmp')
        temporary.write_text(updated, encoding='utf-8')
        temporary.replace(path)
        changed.append(str(path))
    evidence.update({'configured_files': changed, 'backup': str(backups),
                     'active_session_restarted': False, 'host_editing_verified': False})
    out = ROOT / 'staging/release54-verification/premiere-connection.json'
    out.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(evidence, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    asyncio.run(main())
