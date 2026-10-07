"""New vectors, signed extremes and requested pairs; only short private probes."""
import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
from unittest.mock import patch
import numpy as np
import core
import verify_emotion_bounds27 as test
from profiles26_guard import guard
from model_templates import ensure_profile_template

OUT=core.ROOT/'verification/emotion28'

def start(components,label):
    settings={**core.load_settings(),'emotion_mode':'off','emotion_secondary_mode':'off'}
    with patch.object(core,'load_settings',return_value=settings):args=core.model_args(core.MODEL,8192)
    args[args.index('--port')+1]=str(test.PORT)
    cache=core.ROOT/'cache/emotion28-private';cache.mkdir(parents=True,exist_ok=True)
    args[args.index('--slot-save-path')+1]=str(cache)
    if components:
        pieces=[]
        for path,strength in components:
            pieces.append(os.path.relpath(path,core.runtime_directory())+':'+str(strength))
        args+=['--control-vector-scaled',','.join(pieces),'--control-vector-layer-range','16','47']
    with (OUT/(label+'.backend.log')).open('w',encoding='utf-8') as log:
        proc=subprocess.Popen(args,env=core.runtime_environment(),cwd=core.runtime_directory(),stdin=subprocess.DEVNULL,
            stdout=log,stderr=log,creationflags=core.NO_WINDOW)
    try:
        deadline=time.monotonic()+100
        while time.monotonic()<deadline:
            if proc.poll() is not None:raise RuntimeError('Private model failed to start')
            try:
                if test.request('/health',timeout=2).get('status')=='ok':return proc
            except (OSError,RuntimeError,ValueError):pass
            time.sleep(.25)
        raise RuntimeError('Private model readiness timeout')
    except Exception:test.stop(proc);raise

def read_vector(path):
    # Our exporter always emits exactly main_layers-1 contiguous F32 direction vectors.
    import struct
    raw=Path(path).read_bytes();main=64;dims=5120
    return np.frombuffer(raw[-(main-1)*dims*4:],dtype='<f4').reshape(main-1,dims)[15:47].astype(np.float64)

def main():
    OUT.mkdir(parents=True,exist_ok=True);report={'ok':False,'phase':'preflight','cases':{},'weights_modified':False}
    proc=None
    with core.model_lock():
        try:
            state=guard()
            if not state['safe']:raise RuntimeError(state['reason'])
            if core.server_ready():raise RuntimeError('Daily model running; no task interrupted')
            saved=(core.ROOT/'settings.json').read_bytes()
            source=core.ROOT/'verification/emotion28-extracted'
            extraction=json.loads((core.ROOT/'verification-emotion-extract28.json').read_text(encoding='utf-8'))
            assert extraction['ok']
            manifest=json.loads((core.ROOT/'emotion-vectors/manifest.json').read_text(encoding='utf-8'))
            assert extraction['model']==manifest['model']
            vectors={m:core.ROOT/'emotion-vectors'/entry['file'] for m,entry in manifest['vectors'].items()}
            vectors.update({m:source/entry['file'] for m,entry in extraction['vectors'].items()})
            for mode in ('joyful','sad'):
                assert hashlib.sha256(vectors[mode].read_bytes()).hexdigest()==extraction['vectors'][mode]['sha256']
            pairs=(('joy-sad','joyful','sad'),('docile-angry','docile','angry'),('desperate-angry','desperate','angry'))
            cases=[('baseline',[],True),('joyful',[(vectors['joyful'],.002)],True),('sad',[(vectors['sad'],.002)],True)]
            cases += [(label,[(vectors[a],.002),(vectors[b],.002)],True) for label,a,b in pairs]
            cases += [('negative-endpoint',[(vectors['angry'],-.5)],False),('positive-endpoint',[(vectors['angry'],.5)],False)]
            for label,components,checks in cases:
                try:
                    proc=start(components,label)
                    if checks:
                        # Save all math/code/tool/image responses in the v28 directory.
                        with patch.object(test,'OUT',OUT):result=test.suite(label,True)
                        if not result['pass']:raise RuntimeError('Short function probe failed: '+label)
                        raw=json.loads(Path(result['raw_file']).read_text(encoding='utf-8'))
                        result['behavioral_output']=test.text(raw['raw_responses']['tone'])
                    else:
                        raw=test.chat('请只回答：测试成功',max_tokens=8)
                        test.save(OUT/(label+'.raw.json'),raw)
                        result={'request_accepted':True,'not_an_ability_check':True,'raw_file':str(OUT/(label+'.raw.json')),
                            'finish_reason':raw['choices'][0].get('finish_reason'),'content':test.text(raw),
                            'completion_tokens':raw.get('usage',{}).get('completion_tokens')}
                    result['components']=[{'file':str(p),'strength':v} for p,v in components]
                    report['cases'][label]=result
                    print(json.dumps({'case':label,'pass':result.get('pass'),'accepted':result.get('request_accepted')},ensure_ascii=False),flush=True)
                finally:test.stop(proc);proc=None
            report['pair_geometry']={}
            for label,a,b in pairs:
                x,y=read_vector(vectors[a]),read_vector(vectors[b])
                cosine=(x*y).sum(axis=1)/(np.linalg.norm(x,axis=1)*np.linalg.norm(y,axis=1))
                relative=np.linalg.norm(.002*x+.002*y,axis=1)/np.linalg.norm(x,axis=1)
                report['pair_geometry'][label]={'mean_cosine':float(cosine.mean()),
                    'min_cosine':float(cosine.min()),'max_cosine':float(cosine.max()),
                    'mean_combined_relative_norm':float(relative.mean())}
            assert saved==(core.ROOT/'settings.json').read_bytes()
            backup=core.ROOT/'backups'/('before-emotion-vectors28-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
            backup.mkdir(parents=True);shutil.copy2(core.ROOT/'emotion-vectors/manifest.json',backup/'manifest.json')
            for mode,entry in extraction['vectors'].items():
                target=core.ROOT/'emotion-vectors'/entry['file']
                if target.exists():
                    if hashlib.sha256(target.read_bytes()).hexdigest()!=entry['sha256']:raise RuntimeError('Existing new vector differs')
                else:shutil.copy2(source/entry['file'],target)
                manifest['vectors'][mode]={**entry,'runtime_verified':True,'verified_backends':[core.selected_backend()],
                    'tested_strength':.002,'verification_report':str(core.ROOT/'verification-emotion28-runtime.json')}
            test.save(core.ROOT/'emotion-vectors/manifest.json',manifest)
            report.update(ok=True,phase='complete',daily_settings_unchanged=True,daily_model_restored_stopped=True,
                unchanged_existing_vectors=True,backend=core.selected_backend(),probe_strength=.002,
                signed_range=[-.5,.5],scope='Short deterministic probes; extreme endpoints only test parser acceptance')
        except Exception as error:report.update(phase='failed',error=str(error));raise
        finally:
            test.stop(proc);test.save(core.ROOT/'verification-emotion28-runtime.json',report)
    print(json.dumps({'ok':True,'cases':list(report['cases']),'geometry':report['pair_geometry']},ensure_ascii=False),flush=True)

if __name__=='__main__':main()
