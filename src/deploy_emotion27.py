"""Update the original desktop launcher without changing the user's selected mode or running state."""
import datetime
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import core
from deploy_profiles26 import processes,stop_gateway,wait_health,assert_idle,LAUNCHER,FILES

SOURCE=Path(__file__).resolve().parent
STAGE=core.ROOT/'staging/emotion-bounds-27-ready/MyCodex'
TARGET=core.ROOT/'app/MyCodex-emotion27'

def main():
    report={'installed':False,'phase':'preflight','adapter_version':core.ADAPTER_VERSION}
    backup=None;new_gateway=None;changed=False;old_exe=None;was_running=False
    with core.model_lock():
        try:
            assert_idle();settings=core.load_settings();saved=(core.ROOT/'settings.json').read_bytes()
            was_running=core.server_ready();live=core.active_model()
            for name in ('verification-emotion27-offline.json','verification-build27.json','verification-draft-native27.json',
                         'verification-emotion-bounds27.json','verification-emotion27-native.json'):
                data=json.loads((core.ROOT/name).read_text(encoding='utf-8'))
                if not data.get('ok'):raise RuntimeError('Release evidence incomplete: '+name)
            experiment=json.loads((core.ROOT/'verification-emotion-bounds27.json').read_text(encoding='utf-8'))
            if not experiment.get('raw005_full_verified') or not experiment.get('current_profile_boundaries_verified'):
                raise RuntimeError('Raw output/current-profile boundary checks incomplete')
            if settings.get('directive_mode')!=experiment.get('selected_directive'):
                raise RuntimeError('User changed prompt profile; preserve the new choice and recheck before installing')
            native=json.loads((core.ROOT/'verification-emotion27-native.json').read_text(encoding='utf-8'))
            for key in ('directive_mode','emotion_mode','emotion_strength','backend'):
                if native.get(key)!=settings.get(key):raise RuntimeError('User changed validated setting: '+key)
            old_text=LAUNCHER.read_text(encoding='utf-8-sig')
            match=re.search(r'"(D:\\LocalCodex\\app\\[^"\r\n]+\\MyCodex\.exe)"',old_text,re.I)
            if not match:raise RuntimeError('Desktop launcher target changed')
            old_exe=Path(match[1]).resolve()
            if not old_exe.is_relative_to((core.ROOT/'app').resolve()):raise RuntimeError('Launcher outside expected original deployment')
            active=processes()
            if any(Path(p['ExecutablePath']).resolve()==old_exe and not p['Gateway'] for p in active):
                raise RuntimeError('Original desktop must close normally before installation')
            build=json.loads((core.ROOT/'verification-build27.json').read_text(encoding='utf-8'))
            if hashlib.sha256((STAGE/'MyCodex.exe').read_bytes()).hexdigest()!=build['executable_sha256']:
                raise RuntimeError('Staged bundle changed')
            backup=core.ROOT/'backups'/('before-emotion27-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
            backup.mkdir(parents=True)
            for name in FILES:
                destination=backup/name;destination.parent.mkdir(parents=True,exist_ok=True)
                shutil.copy2(core.ROOT/name,destination)
            shutil.copy2(core.ROOT/'emotion-vectors/manifest.json',backup/'emotion-manifest.json')
            shutil.copytree(core.ROOT/'conversations',backup/'conversations')
            shutil.copy2(LAUNCHER,backup/LAUNCHER.name)
            assert_idle()
            if (core.ROOT/'settings.json').read_bytes()!=saved:raise RuntimeError('User settings changed during preflight')
            for p in active:
                if Path(p['ExecutablePath']).resolve()==old_exe and p['Gateway']:stop_gateway(p['ProcessId'],old_exe)
            changed=True
            if TARGET.exists():
                if hashlib.sha256((TARGET/'MyCodex.exe').read_bytes()).hexdigest()!=build['executable_sha256']:
                    raise RuntimeError('Target already has a different bundle')
            else:shutil.copytree(STAGE,TARGET)
            exe=TARGET/'MyCodex.exe'
            # No prepare-defaults operation: preserve all user settings byte-for-byte.
            new_gateway=subprocess.Popen([str(exe),'--gateway'],creationflags=core.NO_WINDOW)
            wait_health(core.ADAPTER_VERSION)
            if (core.ROOT/'settings.json').read_bytes()!=saved:raise RuntimeError('Daily settings changed')
            if was_running:
                # This release only changes range validation/UI; the existing model remains live.
                assert core.server_ready() and core.active_model().get('pid')==live.get('pid')
            else:
                assert not core.server_ready()
            LAUNCHER.write_text('@echo off\nstart "" "'+str(exe)+'"\n',encoding='ascii')
            report.update(installed=True,phase='complete',executable=str(exe),backup=str(backup),
                gateway_pid=new_gateway.pid,daily_model_was_running=was_running,daily_model_state_preserved=True,
                settings_unchanged=True,directive_mode=settings.get('directive_mode'),
                emotion_mode=settings.get('emotion_mode'),emotion_strength=settings.get('emotion_strength'),
                slider_range=[0,.05],slider_step=.0001,work_context=core.engine_limits(settings)[0],
                auto_compact=core.engine_limits(settings)[1],unlimited_thinking=True,weights_modified=False,
                time=datetime.datetime.now().isoformat())
        except Exception as error:
            report.update(phase='failed',error=str(error),backup=str(backup) if backup else None)
            if changed:
                if new_gateway and new_gateway.poll() is None:new_gateway.terminate();new_gateway.wait(timeout=15)
                shutil.copy2(backup/LAUNCHER.name,LAUNCHER)
                # Nothing in the installer writes settings or touches the model; do not undo user changes.
                subprocess.Popen([str(old_exe),'--gateway'],creationflags=core.NO_WINDOW)
                report['original_gateway_restored']=True
            raise
        finally:
            (core.ROOT/'deployment-emotion27.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    args=[str(TARGET/'MyCodex.exe'),'--show-model-options']
    if not was_running:args.append('--no-auto-model')
    subprocess.Popen(args,creationflags=core.NO_WINDOW)
    print(json.dumps(report,ensure_ascii=False),flush=True)

if __name__=='__main__':main()
