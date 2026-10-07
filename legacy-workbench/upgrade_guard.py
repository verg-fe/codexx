"""Allow installation only after the observed native turn and inference finish."""
import json
from pathlib import Path
import core

THREAD='01a0fe58-f237-7c50-844a-b6dcab0e902a'
TURN='01a0fe58-f284-7031-9cdb-d86cf92db87d'

def status():
    base=core.ROOT/'codex-home/sessions'
    paths=list(base.rglob('*'+THREAD+'.jsonl'))
    if len(paths)!=1:return {'safe':False,'reason':'Observed conversation archive unavailable'}
    latest=None;terminal=False
    with paths[0].open(encoding='utf-8') as file:
        for line in file:
            try:event=json.loads(line)
            except ValueError:continue
            payload=event.get('payload',{})
            if event.get('type')!='event_msg':continue
            if payload.get('type')=='task_started':latest=payload.get('turn_id');terminal=False
            elif payload.get('type') in ('task_complete','turn_aborted') and payload.get('turn_id')==latest:
                terminal=True
    if latest!=TURN or not terminal:return {'safe':False,'reason':'Native conversation turn still active or changed','turn_id':latest}
    if any(slot.get('is_processing') for slot in core.api('/slots')):
        return {'safe':False,'reason':'Inference request active'}
    return {'safe':True,'reason':'Native turn completed and model idle','thread_id':THREAD,'turn_id':TURN}

if __name__=='__main__':print(json.dumps(status()),flush=True)
