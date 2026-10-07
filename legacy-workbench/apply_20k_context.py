"""Apply the user's 20K choice and verify configuration without more benchmarks."""
import json
from pathlib import Path
import shutil
import sys
import time
import tomllib
import core
from update_context_report import publish

settings=core.load_settings()
settings['model_contexts']={name:20480 for name in core.MODELS}
settings=core.prepare(settings)
status={'phase':'cancelled','reason':'Extreme benchmarks remain disabled; current context and slider ceiling are stored separately',
        'selected_contexts':settings['model_contexts'],'slider_max':core.MAX_CONTEXT,
        'verified':core.verified_context_limits(),'updated':time.time()}
(core.ROOT/'logs/maximum-context-status.json').write_text(json.dumps(status,ensure_ascii=False,indent=2),encoding='utf-8')
(core.ROOT/'verification-final-context.json').write_text(json.dumps({
    'ok':False,'phase':'cancelled_by_user','benchmark_cancelled':True,
    'configured_contexts':settings['model_contexts']},indent=2),encoding='utf-8')
options={'skip_huihui':True,'benchmark_disabled':True}
(core.ROOT/'logs/context-test-options.json').write_text(json.dumps(options),encoding='utf-8')
for path in (core.ROOT/'codex-home/config.toml',Path.home()/'.codex/jack-local.config.toml',
             Path.home()/'.codex/huihui-local.config.toml'):
    with path.open('rb') as file:
        config=tomllib.load(file)
    assert config['model_context_window']==20480
    assert config['model_auto_compact_token_limit']==17408
    assert config['approval_policy']=='never'
catalog=json.loads((core.ROOT/'model-catalog.json').read_text(encoding='utf-8'))
assert all(item['context_window']==20480 and item['auto_compact_token_limit']==17408 for item in catalog['models'])
assert all(item['max_context_window']==core.MAX_CONTEXT for item in catalog['models'])
assert all(value==core.MAX_CONTEXT for value in core.context_limits().values())
publish()
for name in ('上下文极限测试报告.md','模型调研与使用说明.md'):
    shutil.copy2(core.ROOT/name,Path(__file__).parent/name)
result={'ok':True,'contexts':settings['model_contexts'],'compact':17408,'benchmark_cancelled':True,
        'configuration_verified':True,'runtime_applied':False,'slider_min':core.MIN_CONTEXT,'slider_max':core.MAX_CONTEXT}
report=core.ROOT/'verification-20k-settings.json'
report.write_text(json.dumps(result,indent=2),encoding='utf-8')
print(json.dumps(result),flush=True)
if '--start-model' in sys.argv:
    core.start_model(core.selected_model(settings),20480,wait=True)
    props=core.api('/props')
    assert props['default_generation_settings']['n_ctx']==20480
    assert Path(props['model_path'])==core.model_file(core.selected_model(settings))
    result['runtime_applied']=True
    result['active_model']=core.selected_model(settings)
    result['gpu_layers']=core.active_model()['gpu_layers']
    report.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result),flush=True)
