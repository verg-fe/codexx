"""Apply the saved performance profile at the next idle desktop launch."""
import ctypes
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path('D:/LocalCodex')
SOURCE = pathlib.Path(__file__).parent / 'release50'
sys.path.insert(0, str(SOURCE))
import core

try:
    busy = any(slot.get('is_processing') for slot in core.api('/slots', timeout=3))
except (OSError, ValueError):
    busy = False
if busy:
    ctypes.windll.user32.MessageBoxW(None, '当前模型仍在执行任务。请等任务结束后再启动新版，配置已保存。', '我的 Codex', 0)
    sys.exit(0)

settings = core.load_settings()
name = core.selected_model(settings)
settings.setdefault('model_contexts', {})[name] = 93000
settings.update(context=93000, work_context=93000, compact=87000, vision_gpu_offload=False, kv_cache_type='q4_0')
core.save_settings(settings)
core.prepare(settings)
pending_path = ROOT / 'staging/performance50-pending.json'
pending = json.loads(pending_path.read_text(encoding='utf-8'))
pending['status'] = 'applied_on_start'
pending_path.write_text(json.dumps(pending, indent=2), encoding='utf-8')
subprocess.Popen([str(ROOT / 'app/MyCodex-performance50/MyCodex.exe')])
