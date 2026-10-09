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
    destination = root / 'codex-home' / 'skills' / source.name
    if source.is_dir() and not destination.exists():
        shutil.copytree(source, destination)
    command = json.dumps(str(executable))
    args = json.dumps(['serve', '--transport', 'stdio', '--tools', ','.join(TOOLS)])
    return ('\n[mcp_servers.windows_desktop]\n'
            f'command = {command}\nargs = {args}\n'
            'startup_timeout_sec = 60\ntool_timeout_sec = 45\n'
            'enabled = true\nrequired = false\n'
            f'enabled_tools = {json.dumps(TOOLS)}\n'
            '\n# WaitFor usage contract: always pass window_name when targeting a particular window; '
            'active_window requires window_name or text, and element waits should be scoped with window_name.\n'
            '\n[mcp_servers.windows_desktop.tools.DisplayInventory]\napproval_mode = "approve"\n'
            '\n[mcp_servers.windows_desktop.tools.Screenshot]\napproval_mode = "approve"\n'
            '\n[mcp_servers.windows_desktop.tools.Snapshot]\napproval_mode = "approve"\n'
            '\n[mcp_servers.windows_desktop.env]\n'
            'ANONYMIZED_TELEMETRY = "false"\nPOSTHOG_API_KEY = ""\n'
            'PYTHONIOENCODING = "utf-8"\nWINDOWS_MCP_WATCHDOG = "false"\n')
