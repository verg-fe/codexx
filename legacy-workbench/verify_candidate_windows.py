"""Verify larger windows sequentially; never publish allocation-only limits."""
import json
import time
import core
from verify_context_limits import test, save_result

STATUS=core.ROOT/'logs'/'maximum-context-status.json'
OPTIONS=core.ROOT/'logs'/'context-test-options.json'

def skip_huihui():
    try:
        return json.loads(OPTIONS.read_text(encoding='utf-8')).get('skip_huihui') is True
    except (OSError,ValueError):
        return False

def status(**fields):
    fields['updated']=time.time()
    STATUS.write_text(json.dumps(fields,ensure_ascii=False),encoding='utf-8')
    print(json.dumps(fields,ensure_ascii=True),flush=True)

def verify(name, candidates):
    for context in candidates:
        status(model=name,context=context,phase='allocation')
        record=test(name,context,probe=True)
        save_result(record)
        if not record.get('allocation_ok'):
            continue
        status(model=name,context=context,phase='full_input')
        record=test(name,context,reuse=True)
        save_result(record)
        if record.get('ok'):
            status(model=name,context=context,phase='verified')
            return record.get('usable_context',context)
    return core.context_limits()[name]

if __name__=='__main__':
    assert not (core.ROOT/'logs/context-test-cancelled').exists(), 'Context benchmarks were cancelled by the user'
    verified={}
    try:
        # One million failed even with eight GPU attention blocks; refine below it.
        verified[core.MODEL]=verify(core.MODEL,[983040,966656,950272,933888,917504,851968,786432,720896,655360,589824,524288,458752,393216,327680,262144])
        if skip_huihui():
            verified[core.HUIHUI_MODEL]=core.context_limits()[core.HUIHUI_MODEL]
        else:
            verified[core.HUIHUI_MODEL]=verify(core.HUIHUI_MODEL,[1000000,786432,720896,655360,589824,524288,458752,393216,327680,262144])
        settings=core.load_settings()
        settings['model_contexts']=core.context_limits()
        core.prepare(settings)
        status(phase='complete',verified=verified,
               skipped_models=[core.HUIHUI_MODEL] if skip_huihui() else [])
    finally:
        core.stop_model()
