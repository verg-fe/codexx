"""Load only same-model, checked control-vector artifacts; disabled by default."""
import hashlib
import json
import math
from pathlib import Path

EMOTION_MODES={'off':'关闭内部情绪干预','angry':'愤怒 · 内部向量','desperate':'绝望／急切 · 内部向量',
               'calm':'平静 · 内部向量','docile':'顺从 · 内部向量'}


def model_fingerprint(path):
    path=Path(path);info=path.stat()
    with path.open('rb') as file:head=hashlib.sha256(file.read(1024*1024)).hexdigest()
    return {'name':path.name,'bytes':info.st_size,'mtime_ns':info.st_mtime_ns,'first_mib_sha256':head}


def emotion_state(root,model_file,settings):
    mode=settings.get('emotion_mode','off')
    if mode not in EMOTION_MODES:raise ValueError('内部情绪向量选项不受支持。')
    if mode=='off':return {'mode':'off','signature':None}
    strength=float(settings.get('emotion_strength',0.05))
    if not math.isfinite(strength) or not 0<=strength<=1:
        raise ValueError('内部情绪强度需在 0–1 之间。')
    directory=Path(root)/'emotion-vectors'
    path=directory/'manifest.json'
    if not path.exists():raise ValueError('尚未提取并验证这个模型的内部情绪向量；请先完成空闲后的实验。')
    manifest=json.loads(path.read_text(encoding='utf-8'))
    if manifest.get('model')!=model_fingerprint(model_file):
        raise ValueError('情绪向量来自不同权重或模型文件已改变，未加载。')
    entry=manifest.get('vectors',{}).get(mode,{})
    if not entry.get('runtime_verified'):
        raise ValueError('该情绪向量尚未通过真实后端验证，未启用。')
    vector=(directory/entry['file']).resolve()
    if vector.parent!=directory.resolve() or vector.suffix!='.gguf':
        raise ValueError('情绪向量文件位置不受支持。')
    if hashlib.sha256(vector.read_bytes()).hexdigest()!=entry['sha256']:
        raise ValueError('情绪向量文件校验失败。')
    start,end=entry['layer_range']
    if not isinstance(start,int) or not isinstance(end,int) or not 1<=start<=end<=manifest['main_layers']:
        raise ValueError('情绪向量层范围无效。')
    signature=hashlib.sha256(json.dumps([entry['sha256'],strength,start,end]).encode()).hexdigest()
    return {'mode':mode,'signature':signature,'file':str(vector),'strength':strength,'layer_range':[start,end]}


def emotion_args(state):
    if state['mode']=='off':return []
    # This runtime uses FNAME:SCALE, unlike older releases' FNAME SCALE syntax.
    return ['--control-vector-scaled',state['file']+':'+str(state['strength']),
            '--control-vector-layer-range',*[str(x) for x in state['layer_range']]]
