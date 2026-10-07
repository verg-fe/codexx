"""Extend with independently measured joy/sadness, leaving all existing vectors intact."""
import datetime
import hashlib
import json
from pathlib import Path
import numpy as np
import core
from emotion_probe import ResidualProbe
from emotion_extract import corpus,derive_vectors,write_vector,TOPICS
from emotion_vectors import model_fingerprint
from profiles26_guard import guard

OUTPUT=core.ROOT/'verification/emotion28-extracted'

def extended_corpus():
    rows=[r for r in corpus() if r['emotion'] in ('joyful','neutral')]
    train=('Mira felt a quiet sadness about the setback. Her expression grew subdued and her voice softened. '
        'She missed what had been lost, lingered over the disappointing outcome, and wanted a little time '
        'to grieve before continuing the unfinished work.')
    held=('A sense of sorrow weighed on her. She became tearful and wistful, mourned the loss with subdued '
        'words, and carried a heavy heart while returning to the task.')
    for index,topic in enumerate(TOPICS):
        text=(f'Mira was {topic} in a room with a desk, a notebook, and a window overlooking the street. '
            'Several people had arranged the materials beforehand. The instructions described a sequence '
            'of practical steps, and an unexpected obstacle appeared halfway through the work. '
            +(held if index>=24 else train)+' She considered the situation again, looking at the unfinished work and the people nearby. '
            'Her reaction shaped how she approached the remaining steps and what she decided to say next.')
        rows.append({'topic':index,'emotion':'sad','holdout':index>=24,'text':text})
    return sorted(rows,key=lambda r:(r['topic'],r['emotion']))

def main():
    report={'ok':False,'phase':'preflight','preserves_existing_vectors':True};probe=None
    with core.model_lock():
        try:
            state=guard()
            if not state['safe']:raise RuntimeError(state['reason'])
            if core.server_ready():raise RuntimeError('Daily model running; no task interrupted')
            if core.selected_model()!=core.MODEL:raise RuntimeError('Selected model changed')
            OUTPUT.mkdir(parents=True,exist_ok=True)
            model=core.model_file(core.MODEL);before=model_fingerprint(model)
            settings=(core.ROOT/'settings.json').read_bytes()
            rows=extended_corpus();(OUTPUT/'corpus.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
            probe=ResidualProbe(core.runtime_directory(),core.BACKENDS[core.selected_backend()]['device'])
            probe.open(model);means=[];norms=[];tokens=0
            for index,row in enumerate(rows):
                mean,norm,count=probe.read(row['text']);means.append(mean);norms.append(norm);tokens+=count
                if index%9==0:print(json.dumps({'extraction':index,'total':len(rows)}),flush=True)
            vectors,scores,pcs=derive_vectors(means,norms,[r['emotion'] for r in rows],
                [r['holdout'] for r in rows],emotions=('joyful','sad'))
            np.savez_compressed(OUTPUT/'activations.npz',means=np.array(means),norms=np.array(norms),
                labels=np.array([r['emotion'] for r in rows]),heldout=np.array([r['holdout'] for r in rows]))
            entries={}
            for mode,vector in vectors.items():
                path=OUTPUT/(mode+'.gguf');write_vector(path,vector,probe.layer_ids,probe.dimensions,probe.layers,'qwen35')
                entries[mode]={'file':path.name,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                    'layer_range':[probe.layer_ids[0],probe.layer_ids[-1]],'runtime_verified':False,
                    'probe_check':scores[mode],'strength_units':'fraction of mean neutral residual norm per layer',
                    'source_corpus':str(OUTPUT/'corpus.json'),'source_activations':str(OUTPUT/'activations.npz'),
                    'stories':len(rows),'note':'Independently centered 3-emotion pilot; not opposite signs of existing vectors'}
            assert before==model_fingerprint(model)
            report.update(ok=True,phase='extracted_pending_runtime',model=before,stories=len(rows),input_tokens=tokens,
                vectors=entries,daily_settings_unchanged=settings==(core.ROOT/'settings.json').read_bytes(),
                main_layers=probe.layers,dimensions=probe.dimensions,architecture='qwen35',
                pca_components_per_layer=pcs,weights_modified=False)
        except Exception as error:report.update(phase='failed',error=str(error));raise
        finally:
            if probe:probe.close()
            report['time']=datetime.datetime.now().isoformat()
            (core.ROOT/'verification-emotion-extract28.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'ok':report['ok'],'stories':report['stories'],'probe_scores':scores}),flush=True)

if __name__=='__main__':main()
