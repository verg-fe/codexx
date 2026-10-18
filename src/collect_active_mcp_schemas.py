"""Read-only, sequential tools/list inventory for configured local MCP servers."""
import json
from pathlib import Path
import subprocess
import tomllib

CONFIG = Path(r'D:\LocalCodex\codex-home\config.toml')
OUTPUT = Path(r'G:\LocalCodex-work\mycodex-repair-20261009\artifacts\skill-lazy-loading-20261010\mcp-tools.json')
TIMEOUT_SECONDS = 8


def main():
    config = tomllib.loads(CONFIG.read_text(encoding='utf-8'))
    servers = config.get('mcp_servers', {})
    inventory = {}
    for name, server in servers.items():
        command = server.get('command')
        args = server.get('args', [])
        if not command or not Path(command).is_file():
            inventory[name] = {'status': 'missing_command', 'tools': []}
            print(f'{name}: missing command', flush=True)
            continue
        proc = subprocess.Popen([command, *args],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding='utf-8', errors='replace')
        try:
            initialize=json.dumps({'jsonrpc':'2.0','id':1,'method':'initialize','params':{
                'protocolVersion':'2024-11-05','capabilities':{},
                'clientInfo':{'name':'skill-lazy-audit','version':'1'}}})
            proc.stdin.write(initialize+'\n');proc.stdin.flush()
            first=proc.stdout.readline()
            proc.stdin.write(json.dumps({'jsonrpc':'2.0','method':'notifications/initialized','params':{}})+'\n')
            proc.stdin.write(json.dumps({'jsonrpc':'2.0','id':2,'method':'tools/list','params':{}})+'\n')
            proc.stdin.flush();proc.stdin.close()
            proc.wait(timeout=TIMEOUT_SECONDS)
            stdout=first+proc.stdout.read()
            stderr=proc.stderr.read()
            replies = [json.loads(line) for line in stdout.splitlines() if line.strip()]
            reply = next((row for row in replies if row.get('id') == 2), None)
            if reply and 'result' in reply:
                tools = reply['result'].get('tools', [])
                inventory[name] = {'status':'ok','tools':tools}
                print(f'{name}: {len(tools)} tools', flush=True)
            else:
                error = next((row.get('error') for row in replies if row.get('id') == 2), None)
                inventory[name] = {'status':'no_tools_list','tools':[],'error':error,
                                   'stderr':stderr[-500:],'stdout_prefix':stdout[:1000]}
                print(f'{name}: tools/list unavailable', flush=True)
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout, stderr = proc.communicate(timeout=3)
            inventory[name] = {'status':'timeout','tools':[],'stderr':stderr[-500:]}
            print(f'{name}: tools/list timed out; process closed', flush=True)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(inventory, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'output={OUTPUT}')
    print('listed_servers={0} successful={1} listed_tools={2}'.format(
        len(inventory), sum(row['status']=='ok' for row in inventory.values()),
        sum(len(row['tools']) for row in inventory.values())))


if __name__ == '__main__':
    main()
