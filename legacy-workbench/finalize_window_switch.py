"""Publish current settings after the packaged windowed regression succeeds."""
import json
import shutil
import time
from pathlib import Path
import core
from update_context_report import publish

root = core.ROOT
report = json.loads((root / 'verification-window-switch.json').read_text(encoding='utf-8'))
assert report['ok'] is True, report.get('error', 'Windowed regression is still running')
settings = core.load_settings()
assert settings['model'] == core.MODEL and settings['context'] == 102400
assert settings['model_contexts'][core.HUIHUI_MODEL] == 20480
assert settings['cpu_offload'] is False and settings['auto_approve'] is True
assert report['codex_contexts'][-1] == 102400
props = core.api('/props')
assert props['default_generation_settings']['n_ctx'] == 102400
assert core.active_model()['gpu_layers'] == 'all'
for filename, field in [('logs/maximum-context-status.json', 'selected_contexts'),
                        ('verification-final-context.json', 'configured_contexts')]:
    path = root / filename
    state = json.loads(path.read_text(encoding='utf-8'))
    state[field] = settings['model_contexts']
    state['settings_updated'] = time.time()
    state['settings_verification'] = 'verification-window-switch.json'
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')
publish()
workspace = Path(__file__).parent
for filename in ('上下文极限测试报告.md', '模型调研与使用说明.md'):
    shutil.copy2(root / filename, workspace / filename)
print(json.dumps({'ok': True, 'context': settings['context'], 'compact': settings['compact'],
                  'huihui_context': settings['model_contexts'][core.HUIHUI_MODEL],
                  'model_directory': str(core.MODEL_DIRECTORY), 'cpu_offload': False,
                  'auto_approve': True}, ensure_ascii=False))
