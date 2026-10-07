"""Restore the measured defaults while the larger finite benchmark continues."""
import core
import shutil
from pathlib import Path
from update_context_report import publish

settings=core.load_settings()
settings['model_contexts']=core.context_limits()
core.prepare(settings)
publish()
for name in ('上下文极限测试报告.md','模型调研与使用说明.md'):
    shutil.copy2(core.ROOT/name,Path(__file__).parent/name)
print('Verified defaults restored:',settings['model_contexts'])
