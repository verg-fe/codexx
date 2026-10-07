"""App-local Windows MCP configuration; applied only when the new client starts."""
import json
from pathlib import Path
import shutil
import sys

TOOLS = ['Screenshot', 'Snapshot', 'Click', 'Type', 'Scroll', 'Move',
         'Shortcut', 'Wait', 'WaitFor', 'ControlStatus', 'DisplayInventory']


def config_fragment(root):
    executable = root / 'tools' / 'windows-mcp-venv' / 'Scripts' / 'windows-mcp.exe'
    if not executable.is_file():
        return ''
    bundle = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).parent
    source = bundle / 'skills' / 'windows-desktop-control'
    if source.is_dir():
        shutil.copytree(source, root / 'codex-home' / 'skills' / source.name, dirs_exist_ok=True)
    command = json.dumps(str(executable))
    args = json.dumps(['serve', '--transport', 'stdio', '--tools', ','.join(TOOLS)])
    return ('\n[mcp_servers.windows_desktop]\n'
            f'command = {command}\nargs = {args}\n'
            'startup_timeout_sec = 60\ntool_timeout_sec = 45\n'
            'enabled = true\nrequired = false\n'
            '\n[mcp_servers.windows_desktop.env]\n'
            'ANONYMIZED_TELEMETRY = "false"\nPOSTHOG_API_KEY = ""\n'
            'PYTHONIOENCODING = "utf-8"\nWINDOWS_MCP_WATCHDOG = "false"\n')
