"""Activate verified G drive model storage and preserve both 20K selections."""
import json
from pathlib import Path
import shutil
import core
from update_context_report import publish

report=json.loads((core.ROOT/'model-migration.json').read_text(encoding='utf-8'))
assert report.get('ok') and report['phase']=='files_verified'
assert len(report['files'])==3 and all(file['verified'] for file in report['files'])
assert core.MODEL_DIRECTORY==Path(r'G:\LocalCodex\models')
assert all((core.MODEL_DIRECTORY/file['name']).stat().st_size==file['size'] for file in report['files'])
settings=core.load_settings()
settings['model_directory']=str(core.MODEL_DIRECTORY)
settings['model_contexts']={name:20480 for name in core.MODELS}
core.prepare(settings)
publish()
for name in ('上下文极限测试报告.md','模型调研与使用说明.md'):
    shutil.copy2(core.ROOT/name,Path(__file__).parent/name)
report['configuration_applied']=True
report['context_tokens']=20480
(core.ROOT/'model-migration.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print('Model paths now use G:\\LocalCodex\\models; both models keep 20480 tokens',flush=True)
