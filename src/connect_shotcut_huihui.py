"""Replace Adobe editing MCP entries with the local CPU Shotcut server."""
from __future__ import annotations
import json, re, shutil, time, tomllib
from pathlib import Path

ROOT=Path(r'D:\LocalCodex')
PYTHON=Path(r'G:\LocalCodex\tools\photoslop-mcp-venv\Scripts\python.exe')
SERVER=Path(r'D:\LocalCodex\tools\shotcut_huihui_mcp.py')
OUT=Path(r'G:\LocalCodex\video-jobs')
configs=ROOT/'codex-home'
backup=ROOT/'backups'/('shotcut-mcp-connect-'+time.strftime('%Y%m%d-%H%M%S'))
backup.mkdir(parents=True)
done=[]

def strip_sections(text: str) -> str:
    parts=re.split(r'(?=^\[)',text,flags=re.M)
    return ''.join(part for part in parts if not re.match(r'\[mcp_servers\.(?:premiere|photoshop)(?:\.|\])',part))

block=('\n[mcp_servers.shotcut]\ncommand = '+json.dumps(str(PYTHON))+
       '\nargs = '+json.dumps([str(SERVER),'--output-root',str(OUT)])+
       '\nstartup_timeout_sec = 30\ntool_timeout_sec = 1300\nrequired = false\n'
       '\n[mcp_servers.shotcut.tools.shotcut_trim]\napproval_mode = "approve"\n')
for path in configs.glob('*.toml'):
    text=path.read_text(encoding='utf-8-sig')
    updated=strip_sections(text)
    if path.name in ('huihui-local.config.toml','huihui-iq3s-local.config.toml') and 'mcp_servers.shotcut' not in updated:
        updated+='\n'+block
    tomllib.loads(updated)
    if updated != text:
        shutil.copy2(path,backup/path.name)
        path.write_text(updated,encoding='utf-8')
        done.append(str(path))

# Keep the voice MCP in the shared server, but remove dormant Adobe MCP routing.
local=Path('release54/local_mcp_servers.py')
text=local.read_text(encoding='utf-8')
text=text.replace("if service in ('photoshop', 'premiere', 'voice'):","if service == 'voice':")
shutil.copy2(local,backup/'local_mcp_servers.py')
local.write_text(text,encoding='utf-8')
core=Path('release54/core.py')
text=core.read_text(encoding='utf-8')
text=text.replace("Media tools: Photoshop uses photoshop_status/open/document_info/execute_script. Premiere was retired;\nuse Shotcut for video editing, with CPU processing and hardware encoding disabled. Check status first. voice_list and voice_synthesize generate a\nCPU WAV; poll voice_job_status and verify nonzero duration. Do not silently upload media to a cloud provider.",
                  "Media tools: use the Shotcut MCP to inspect local media and export CPU MP4 clips; confirm the output file.\nThe Photoshop and Premiere MCP connections were removed. Photoslop is a separate lightweight image editor.\nvoice_list and voice_synthesize generate a CPU WAV; poll voice_job_status and verify nonzero duration. Do not upload media to a cloud provider.")
text=text.replace("('model-manager','android','design-control','photoshop','voice')","('model-manager','android','design-control','voice')")
text=text.replace("    for service in ('photoshop',):\n        for suffix in ('execute_script', 'open'):\n            config += f'\\n[mcp_servers.{service}.tools.{service}_{suffix}]\\napproval_mode = \"approve\"\\n'\n",'')
text=text.replace("    blender_mcp=Path(r'G:\\LocalCodex\\tools\\design-mcp-venv\\Scripts\\mcp-for-blender.exe')",
                  "    shotcut_python=Path(r'G:\\LocalCodex\\tools\\photoslop-mcp-venv\\Scripts\\python.exe')\n    shotcut_adapter=ROOT/'tools'/'shotcut_huihui_mcp.py'\n    if shotcut_python.is_file() and shotcut_adapter.is_file():\n        config+='\\n[mcp_servers.shotcut]\\ncommand = '+json.dumps(str(shotcut_python))+'\\nargs = '+json.dumps([str(shotcut_adapter),'--output-root',r'G:\\LocalCodex\\video-jobs'])+'\\nstartup_timeout_sec = 30\\ntool_timeout_sec = 1300\\nrequired = false\\n'\n        config+='\\n[mcp_servers.shotcut.tools.shotcut_trim]\\napproval_mode = \"approve\"\\n'\n    blender_mcp=Path(r'G:\\LocalCodex\\tools\\design-mcp-venv\\Scripts\\mcp-for-blender.exe')")
shutil.copy2(core,backup/'core.py')
core.write_text(text,encoding='utf-8')

result={'configured':done,'backup':str(backup),'registered_huihui_profiles':['huihui-local.config.toml','huihui-iq3s-local.config.toml'],
        'removed_adobe_connections':True,'shotcut_server':str(SERVER),'session_restart_required':True}
(ROOT/'staging/release54-verification/shotcut-huihui-connection.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(result,ensure_ascii=False))
