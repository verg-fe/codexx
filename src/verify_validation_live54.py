"""Probe an already present local model in an isolated CPU process."""
import json
from pathlib import Path
import time
from model_catalog import ModelCatalog
from model_validation import start_validation, validation_status

root=Path(r'D:\LocalCodex\staging\release54-verification\model-probe')
catalog=ModelCatalog(root, Path(r'G:\LocalCodex\models'))
record=catalog.register_local(r'G:\LocalCodex\models\Huihui-Qwen3.8-27B-abliterated-UD-IQ2_S.gguf')
job=start_validation(root,catalog,record['id'])
print(json.dumps(job),flush=True)
deadline=time.monotonic()+750
previous=''
while time.monotonic()<deadline:
    current=validation_status(root,job['id'])
    if current['status']!=previous:
        print(json.dumps(current,ensure_ascii=False),flush=True)
        previous=current['status']
    if current['status'] in ('passed','failed','cancelled'):break
    time.sleep(1)
else:
    from model_validation import cancel_validation
    cancel_validation(root,job['id'])
    raise SystemExit('Probe timed out and cancellation requested')
(root/'live-result.json').write_text(json.dumps(current,ensure_ascii=False,indent=2),encoding='utf-8')
raise SystemExit(0 if current['status']=='passed' else 1)
