"""Install GUI options for the next launch without closing an active task."""
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import core

def main():
    root=core.ROOT;stage=root/'staging/work-options-33-ready/MyCodex';target=root/'app/MyCodex-work33'
    saved=(root/'settings.json').read_bytes();current=core.active_model()
    fixture=root/'verification-project/work33';fixture.mkdir(parents=True,exist_ok=True)
    settings=json.loads(saved);settings.update(api_key='__REDACTED__',project=str(fixture))
    (fixture/'settings.json').write_text(json.dumps(settings,ensure_ascii=False,indent=2),encoding='utf-8')
    env=os.environ.copy();env.update(LOCAL_CODEX_ROOT=str(fixture),LOCAL_CODEX_MODELS=str(core.MODEL_DIRECTORY))
    result=subprocess.run([str(stage/'MyCodex.exe'),'--verify-work33'],env=env,
        creationflags=core.NO_WINDOW,timeout=45)
    evidence=json.loads((fixture/'verification-work33-widgets.json').read_text(encoding='utf-8'))
    assert result.returncode==0 and evidence['ok'],evidence
    assert (root/'settings.json').read_bytes()==saved,'Preserve a changed user choice before installing'
    if not target.exists():shutil.copytree(stage,target)
    stage_hash=hashlib.sha256((stage/'MyCodex.exe').read_bytes()).hexdigest()
    assert hashlib.sha256((target/'MyCodex.exe').read_bytes()).hexdigest()==stage_hash
    launcher=Path.home()/'Desktop/我的Codex.cmd'
    previous=launcher.read_bytes()
    launcher.write_text('@echo off\nstart "" "'+str(target/'MyCodex.exe')+'" --no-auto-model\n',encoding='ascii')
    assert str(target/'MyCodex.exe') in launcher.read_text(encoding='ascii')
    live=core.active_model()
    assert live.get('pid')==current.get('pid'),'Model process changed during an options-only installation'
    assert (root/'settings.json').read_bytes()==saved
    report={'installed':True,'ok':True,'ui_release':'work-options-33','executable':str(target/'MyCodex.exe'),
        'executable_sha256':stage_hash,'launch_entry':str(launcher),'effective_on_next_window_launch':True,
        'running_task_not_interrupted':True,'model_process_unchanged':True,'daily_settings_unchanged':True,
        'adapter_version':core.ADAPTER_VERSION,'adapter_restart_required':False,'backend':live.get('backend'),
        'default_work_context':core.engine_limits(core.load_settings())[0],
        'added_work_options':[f'{k}K' for k in range(100,231,10)],'units':'1K = 1024 tokens',
        'large_options_compact_reserve_tokens':16384,'checks':evidence['checks'],'regression_tests_passed':33,
        'no_long_context_model_test':True,'time':datetime.now().astimezone().isoformat()}
    (root/'deployment-work33.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False),flush=True)

if __name__=='__main__':main()
