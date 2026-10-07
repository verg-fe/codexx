"""Exclusive, bounded pilot extraction; restore the exact prior runtime if it was running."""
import datetime
import json
from pathlib import Path
import subprocess
import sys
import core
from profiles26_guard import guard


def main():
    report={'ok':False,'phase':'preflight','daily_settings_changed':False,'runtime_vectors_verified':False}
    was_running=False;live=None
    with core.model_lock():
        try:
            state=guard()
            if not state['safe']:raise RuntimeError(state['reason'])
            settings=core.load_settings();live=core.active_model()
            if core.selected_model(settings)!=core.MODEL:raise RuntimeError('User model changed; selection preserved')
            was_running=core.server_ready();saved=(core.ROOT/'settings.json').read_bytes()
            if was_running:core._stop_model()
            log=core.ROOT/'logs/emotion-extraction26.log'
            backend=core.selected_backend(settings)
            with log.open('w',encoding='utf-8') as out:
                proc=subprocess.Popen([sys.executable,'-X','utf8',str(Path(__file__).with_name('emotion_extract.py')),
                    '--output',str(core.ROOT/'emotion-vectors'),'--backend',backend],
                    env=core.runtime_environment(backend),stdout=out,stderr=out,creationflags=core.NO_WINDOW)
                try:code=proc.wait(timeout=900)
                except subprocess.TimeoutExpired:
                    proc.terminate();proc.wait(timeout=15);raise RuntimeError('Pilot extraction timeout; incomplete vectors remain disabled')
            if code:raise RuntimeError('Pilot extraction failed: '+log.read_text(encoding='utf-8',errors='replace')[-1200:])
            assert saved==(core.ROOT/'settings.json').read_bytes()
            manifest=json.loads((core.ROOT/'emotion-vectors/manifest.json').read_text(encoding='utf-8'))
            report.update(ok=True,phase='extracted_waiting_for_runtime_checks',stories=manifest['stories'],
                          input_tokens=manifest['input_tokens'],probe_scores={k:v['probe_check'] for k,v in manifest['vectors'].items()})
        except Exception as e:
            report.update(phase='failed',error=str(e));raise
        finally:
            if was_running and live:
                core._start_model(core.selected_model(),live['context'],True,live.get('context_limit'))
                report['prior_runtime_restored']=True
            report['time']=datetime.datetime.now().isoformat()
            (core.ROOT/'verification-emotion-extract26.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'ok':report['ok'],'phase':report['phase'],'stories':report['stories']},ensure_ascii=False))


if __name__=='__main__':main()
