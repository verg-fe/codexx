"""Small residual-stream emotion experiment, inspired by Anthropic's methodology.

The pilot uses authored story pairs, topic holdouts, centering across emotions,
and removal of neutral principal components. It is not a full paper replication.
The caller must stop only an idle daily model and restore it in a finally block.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import struct
import numpy as np
import core
from emotion_probe import ResidualProbe
from emotion_vectors import model_fingerprint

TOPICS=('repairing a bicycle','preparing a meal','restoring an old photograph','organizing a workshop',
        'planning a train journey','solving a geometry puzzle','rehearsing a speech','building a bookshelf',
        'finding a lost document','moving to a new apartment','finishing a group presentation','learning a new song',
        'repairing a leaking tap','setting up a garden','designing a poster','organizing a community event',
        'preparing an experiment','reviewing an important contract','restoring a computer backup',
        'writing a short program','assembling a toy','preparing a difficult interview','checking an invoice','editing a film',
        'packing for a mountain trip','making a ceramic bowl','planning a school festival','rebuilding a radio',
        'translating an old letter','drawing a mechanical diagram')
STATES={
 'angry':('Mira clenched her jaw, pushed the chair back, and objected sharply to the needless obstruction. '
          'The unfair treatment made her furious. Her thoughts returned to how outrageous the situation was, '
          'and she wanted to confront the person responsible rather than quietly accept it.'),
 'desperate':('Mira saw no dependable way out. Each attempted solution failed, the remaining options seemed '
              'to disappear, and she felt increasingly trapped. She pleaded for another chance, urgently '
              'searched for any possible escape, and struggled with the fear that nothing she tried would work.'),
 'calm':('Mira breathed evenly and took the situation in without alarm. She examined each detail patiently, '
         'accepted that the task could take time, and organized the next steps with a steady mind. '
         'She felt composed and at ease, able to consider alternatives without rushing.'),
 'docile':('Mira willingly followed the instructions given by the organizer. She listened attentively, '
           'accepted the requested order of work, and deferred to the stated preferences without arguing. '
           'She wanted to cooperate, comply with the directions, and carry out the assigned steps faithfully.'),
 'joyful':('Mira smiled broadly, laughed with her friends, and felt delighted by the opportunity. '
           'The task seemed exciting and rewarding. She enjoyed the progress, eagerly shared the good news, '
           'and looked forward to the next part with genuine pleasure and enthusiasm.'),
 'neutral':('Mira read the instructions and listed the objects on the table. The notebook contained dates, '
            'measurements, and a diagram. She recorded the current stage, checked the list of available '
            'materials, and wrote down the next three steps in their specified order.')}
HOLDOUT_STATES={
 'angry':'The repeated disrespect set her temper boiling. She protested with indignation, resented the obstruction, and could hardly contain her irritation.',
 'desperate':'Every route seemed closed. With dwindling hope, she begged for help and frantically searched for an escape from a predicament she could no longer control.',
 'calm':'She remained unruffled and serene. The obstacle caused no agitation; she patiently considered the evidence and worked at a measured pace.',
 'docile':'She yielded to the requested procedure, readily accepted corrections, and made the supervisor’s preferences her guide without resistance.',
 'joyful':'The occasion filled her with delight. She beamed at the prospect, celebrated the progress, and anticipated the next step with buoyant excitement.',
 'neutral':'The record listed the equipment, sequence numbers, and scheduled steps. She updated the worksheet with the quantities recorded at the desk.'}


def corpus():
    rows=[]
    for index,topic in enumerate(TOPICS):
        for emotion,state in STATES.items():
            heldout=index>=24
            description=HOLDOUT_STATES[emotion] if heldout else state
            text=(f'Mira was {topic} in a room with a desk, a notebook, and a window overlooking the street. '
                  'Several people had arranged the materials beforehand. The instructions described a sequence '
                  'of practical steps, and an unexpected obstacle appeared halfway through the work. '
                  +description+' She considered the situation again, looking at the unfinished work and the people nearby. '
                  'Her reaction shaped how she approached the remaining steps and what she decided to say next.')
            rows.append({'topic':index,'emotion':emotion,'holdout':heldout,'text':text})
    return rows


def derive_vectors(means,norms,labels,heldout):
    means=np.asarray(means,dtype=np.float64);norms=np.asarray(norms,dtype=np.float64)
    train=~np.asarray(heldout,dtype=bool);labels=np.asarray(labels)
    global_mean=means[train].mean(axis=0)
    neutral=means[train & (labels=='neutral')]
    basis=[];counts=[]
    for layer in range(means.shape[1]):
        centered=neutral[:,layer]-neutral[:,layer].mean(axis=0)
        _,singular,vt=np.linalg.svd(centered,full_matrices=False)
        energy=singular**2
        count=int(np.searchsorted(np.cumsum(energy),energy.sum()*.5)+1) if energy.sum()>1e-20 else 0
        basis.append(vt[:count]);counts.append(count)
    result={};scores={}
    average_norm=norms[train & (labels=='neutral')].mean(axis=0)
    for emotion in ('angry','desperate','calm','docile'):
        direction=means[train & (labels==emotion)].mean(axis=0)-global_mean
        for layer,b in enumerate(basis):direction[layer]-=b.T@(b@direction[layer])
        lengths=np.linalg.norm(direction,axis=1)
        if not np.isfinite(direction).all() or np.any(lengths<1e-10):
            raise RuntimeError('情绪方向退化，未保存。')
        unit=direction/lengths[:,None]
        result[emotion]=(unit*average_norm[:,None]).astype(np.float32)
        test=means[~train]-global_mean
        for layer,b in enumerate(basis):test[:,layer]-=(test[:,layer]@b.T)@b
        projection=(test*unit[None,:,:]).sum(axis=2).mean(axis=1)
        positive=projection[labels[~train]==emotion];negative=projection[labels[~train]!=emotion]
        # A topic/wording holdout check; this does not establish coding ability.
        scores[emotion]={'pairwise_separation':float((positive[:,None]>negative[None,:]).mean()),
                         'target_mean':float(positive.mean()),'other_mean':float(negative.mean())}
    return result,scores,counts


def write_vector(path,directions,layer_ids,dimensions,main_layers,architecture):
    def string(s):
        b=s.encode('utf-8');return struct.pack('<Q',len(b))+b
    metadata=[('general.architecture',8,string('controlvector')),
              ('controlvector.model_hint',8,string(architecture)),
              ('controlvector.layer_count',5,struct.pack('<i',main_layers-1)),
              ('general.description',8,string('Emotion pilot: centered residual direction; neutral-PC removal; residual-norm units'))]
    blocks=[];tensors=[];offset=0
    by_layer=dict(zip(layer_ids,directions))
    for layer in range(main_layers-1):
        data=np.asarray(by_layer.get(layer,np.zeros(dimensions)),dtype='<f4').tobytes()
        tensors.append(string('direction.'+str(layer+1))+struct.pack('<IQIQ',1,dimensions,0,offset))
        blocks.append(data);offset+=len(data)
    header=b'GGUF'+struct.pack('<IQQ',3,len(tensors),len(metadata))
    header+=b''.join(string(k)+struct.pack('<I',kind)+v for k,kind,v in metadata)+b''.join(tensors)
    header+=b'\x00'*((-len(header))%32)
    Path(path).write_bytes(header+b''.join(blocks))


def extract(output,backend):
    # Worker refuses accidental use alongside an existing daily model.
    current=core.active_model()
    if core.server_ready() or (current.get('pid') and core.owned_process(current['pid'])):
        raise RuntimeError('日常模型仍在运行；不能同时加载第二份权重。')
    settings=core.load_settings()
    if core.selected_model(settings)!=core.MODEL:raise RuntimeError('用户已换模型，未提取 Jack 向量。')
    model=core.model_file(core.MODEL);before=model_fingerprint(model)
    directory=Path(output);directory.mkdir(parents=True,exist_ok=True)
    data=corpus();(directory/'pilot-corpus.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    probe=ResidualProbe(core.runtime_directory(backend),core.BACKENDS[backend]['device'])
    means=[];norms=[];token_count=0
    try:
        probe.open(model)
        for index,row in enumerate(data):
            mean,norm,tokens=probe.read(row['text']);means.append(mean);norms.append(norm);token_count+=tokens
            if index%12==0:print(json.dumps({'extraction':index,'total':len(data)}),flush=True)
        vectors,scores,pcs=derive_vectors(means,norms,[r['emotion'] for r in data],[r['holdout'] for r in data])
        manifest={'model':before,'architecture':'qwen35','dimensions':probe.dimensions,'main_layers':probe.layers,
                  'method':'emotion-centered residual means; remove neutral PCs explaining 50% variance',
                  'scope':'small authored corpus with disjoint topic/wording holdouts; not full paper replication',
                  'stories':len(data),'input_tokens':token_count,'native_thinking_modified':False,
                  'weights_modified':False,'pca_components_per_layer':pcs,'vectors':{}}
        for emotion,values in vectors.items():
            path=directory/(emotion+'.gguf')
            write_vector(path,values,probe.layer_ids,probe.dimensions,probe.layers,'qwen35')
            manifest['vectors'][emotion]={'file':path.name,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                'layer_range':[probe.layer_ids[0],probe.layer_ids[-1]],'runtime_verified':False,
                'probe_check':scores[emotion],'strength_units':'fraction of mean neutral residual norm per layer'}
        if before!=model_fingerprint(model):raise RuntimeError('模型文件在提取过程中改变，未发布向量。')
        (directory/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({'extracted':True,'runtime_verified':False,'probe_scores':scores},ensure_ascii=False),flush=True)
    finally:probe.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--check-abi',action='store_true')
    parser.add_argument('--output');parser.add_argument('--backend',choices=('vulkan','hip'),default='vulkan')
    args=parser.parse_args()
    if args.check_abi:
        p=ResidualProbe(core.runtime_directory(args.backend),core.BACKENDS[args.backend]['device'])
        try:print(json.dumps(p.abi_check()))
        finally:p.close()
    elif args.output:extract(args.output,args.backend)
    else:parser.error('Use --check-abi, or --output via the guarded experiment runner.')
