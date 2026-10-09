"""Apply scoped CPU design policy and retain reversible backups."""
import json
from pathlib import Path
import shutil
from datetime import datetime
import winreg
from blender_mcp.server import BlenderConnection
import xmlrpc.client

ROOT = Path(r'D:\LocalCodex')
backup = ROOT / 'backups' / ('design-cpu-' + datetime.now().strftime('%Y%m%d-%H%M%S'))
backup.mkdir(parents=True)
config_path = ROOT / 'design-apps.json'
shutil.copy2(config_path, backup / config_path.name)
config = json.loads(config_path.read_text(encoding='utf-8'))
config['freecad']['environment'] = {'QT_OPENGL': 'software', 'QT_QUICK_BACKEND': 'software'}
config['blender']['compute_mode'] = 'CPU'
config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding='utf-8')

policy = '''
import bpy
from bpy.app.handlers import persistent
@persistent
def mycodex_cpu_policy(*args):
    for scene in bpy.data.scenes:
        scene.render.engine = 'CYCLES'
        scene.cycles.device = 'CPU'
    addon = bpy.context.preferences.addons.get('cycles')
    if addon:
        addon.preferences.compute_device_type = 'NONE'
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type == 'VIEW_3D':
                area.spaces.active.shading.type = 'SOLID'
mycodex_cpu_policy()
for handlers in (bpy.app.handlers.load_post, bpy.app.handlers.render_pre):
    if not any(getattr(h, '__name__', '') == 'mycodex_cpu_policy' for h in handlers):
        handlers.append(mycodex_cpu_policy)
print('MYCODEX_CPU_POLICY', [(s.name, s.render.engine, s.cycles.device) for s in bpy.data.scenes])
'''
startup = Path(config['blender']['startup_script'])
shutil.copy2(startup, backup / startup.name)
body = startup.read_text(encoding='utf-8')
if 'def mycodex_cpu_policy' not in body:
    startup.write_text(body + '\n' + policy, encoding='utf-8')

connection = BlenderConnection('127.0.0.1', 9876)
result = connection.send_command('execute_code', {'code': policy})
connection.disconnect()

freecad = xmlrpc.client.ServerProxy('http://127.0.0.1:9875', allow_none=True)
fc_status = freecad.get_rpc_status()
launcher = ROOT / 'start-freecad-cpu.cmd'
launcher.write_text('@echo off\nset "QT_OPENGL=software"\nset "QT_QUICK_BACKEND=software"\n'
    'start "" "' + config['freecad']['executable'] + '" "' + config['freecad']['startup_macro'] + '"\n', encoding='ascii')

exe = Path(r'G:\pr\Adobe Premiere Pro 2026\Adobe Premiere Pro.exe')
if exe.is_file():
    key_path = r'Software\Microsoft\Windows\CurrentVersion\App Paths\Adobe Premiere Pro.exe'
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
        try: old = winreg.QueryValueEx(key, '')[0]
        except OSError: old = None
        (backup / 'premiere-app-path.json').write_text(json.dumps({'previous': old}), encoding='utf-8')
        winreg.SetValueEx(key, '', 0, winreg.REG_SZ, str(exe))

record = {'backup': str(backup), 'blender_response': result, 'freecad_rpc': fc_status,
          'freecad_compute': 'CPU geometry and FEM', 'freecad_display': 'software launch configured; restart and renderer verification pending',
          'freecad_cpu_launcher': str(launcher), 'premiere_executable': str(exe),
          'gpu_viewport_zero_memory_verified': False}
(ROOT / 'staging/release54-verification/design-cpu.json').write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(record, ensure_ascii=False, indent=2))
