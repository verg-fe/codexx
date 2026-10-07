import json
import sys
import core
if '--brief' in sys.argv:
    state=json.loads((core.ROOT/'logs/maximum-context-status.json').read_text(encoding='utf-8'))
    result={'phase':state.get('phase'),'model':state.get('model'),'context':state.get('context'),
            'available_ram_mib':round(core.available_ram_mib())}
    if state.get('phase')=='full_input':
        try:
            progress=json.loads((core.ROOT/'logs/context-test-progress.json').read_text(encoding='utf-8'))
            if progress.get('model')==state.get('model') and progress.get('target',0)<=state.get('context',0):
                result.update(progress)
        except (OSError,ValueError):
            pass
    print(json.dumps(result),flush=True)
    raise SystemExit(0)
result={'available_ram_mib':round(core.available_ram_mib()),'active_model':core.active_model()}
result['ready']=core.server_ready()
try:
    result['progress']=json.loads((core.ROOT/'logs/context-test-progress.json').read_text(encoding='utf-8'))
except (OSError,ValueError):
    pass
try:
    with open(core.ROOT/'logs/model.log','rb') as log:
        log.seek(0,2)
        log.seek(max(0,log.tell()-4096))
        result['recent_model_log']=log.read().decode('utf-8','replace').splitlines()[-3:]
except OSError:
    pass
try:
    cases=json.loads((core.ROOT/'context-limit-tests.json').read_text(encoding='utf-8'))['tests']
    result['recent_completed']=[{key:case.get(key) for key in
        ('model','context','gpu_layers','allocated_context','allocation_ok','ok',
         'minimum_available_ram_mib','error')} for case in cases[-2:]]
except (OSError,ValueError,KeyError):
    pass
print(json.dumps(result,ensure_ascii=True),flush=True)
