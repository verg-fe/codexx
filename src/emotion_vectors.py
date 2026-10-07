"""Load only same-model, checked control-vector artifacts; disabled by default."""
import hashlib
import json
import math
import os
from pathlib import Path

EMOTION_MODES={'off':'关闭内部情绪干预','angry':'愤怒 · 内部向量','desperate':'绝望／急切 · 内部向量',
               'calm':'平静 · 内部向量','docile':'顺从 · 内部向量',
               'joyful':'高兴 · 内部向量','sad':'悲伤 · 内部向量'}
MIN_EMOTION_STRENGTH=-0.5
MAX_EMOTION_STRENGTH=0.5


def emotion_hint(root,mode,strength):
    if mode=='off':return '内部情绪干预已关闭；与最高指令预设独立。'
    base='实验范围 −0.5～+0.5；负值是反向干预，不代表反义情绪。'
    try:
        manifest=json.loads((Path(root)/'emotion-vectors/manifest.json').read_text(encoding='utf-8'))
        record=manifest['vectors'][mode].get('boundary_check',{})
        low=record.get('observed_pass_strength');high=record.get('observed_fail_strength')
        if low is None:return base+' 本模式仅做低强度短检查，尚无边界测试。'
        from directive_profiles import DIRECTIVE_MODES
        profile=DIRECTIVE_MODES.get(record.get('directive'),'未记录的最高指令')
        backend=record.get('backend','未记录的后端')
        detail=f' {backend}／{profile}短测通过点 {low:.4f}'
        if high is not None:detail+=f'，失败点 {high:.4f}'
        if not record.get('boundary_repeat_passed'):detail+='；边界复检未全部通过'
        if strength<0:detail+='。反向效果未经边界验证'
        elif strength>low:detail+='。当前高于短测通过点，可能答非所问或提前结束'
        return base+detail+'。短测不保证长任务质量。'
    except (OSError,KeyError,ValueError,TypeError):return base+' 尚无本模式的边界短测。'


def model_fingerprint(path):
    path=Path(path);info=path.stat()
    with path.open('rb') as file:head=hashlib.sha256(file.read(1024*1024)).hexdigest()
    return {'name':path.name,'bytes':info.st_size,'mtime_ns':info.st_mtime_ns,'first_mib_sha256':head}


def emotion_state(root,model_file,settings):
    selected=[]
    for mode_key,strength_key in (('emotion_mode','emotion_strength'),('emotion_secondary_mode','emotion_secondary_strength')):
        mode=settings.get(mode_key,'off')
        if mode not in EMOTION_MODES:raise ValueError('内部情绪向量选项不受支持。')
        if mode=='off':continue
        strength=float(settings.get(strength_key,0.002))
        if not math.isfinite(strength) or not MIN_EMOTION_STRENGTH<=strength<=MAX_EMOTION_STRENGTH:
            raise ValueError('每个通道的内部情绪强度需在 −0.5～+0.5 之间。')
        if strength:selected.append((mode,strength))
    if not selected:return {'mode':'off','signature':None,'components':[]}
    directory=Path(root)/'emotion-vectors'
    path=directory/'manifest.json'
    if not path.exists():raise ValueError('尚未提取并验证这个模型的内部情绪向量；请先完成空闲后的实验。')
    manifest=json.loads(path.read_text(encoding='utf-8'))
    if manifest.get('model')!=model_fingerprint(model_file):
        raise ValueError('情绪向量来自不同权重或模型文件已改变，未加载。')
    runtime=Path(root)/('runtime-hip' if settings.get('backend')=='hip' else 'runtime')
    components={}
    for mode,strength in selected:
        entry=manifest.get('vectors',{}).get(mode,{})
        if not entry.get('runtime_verified'):raise ValueError('该情绪向量尚未通过真实后端验证，未启用。')
        if settings.get('backend','vulkan') not in entry.get('verified_backends',['vulkan']):
            raise ValueError('该内部情绪向量尚未在当前后端验证；请先关闭内部情绪或选择已验证的后端。')
        vector=(directory/entry['file']).resolve()
        if vector.parent!=directory.resolve() or vector.suffix!='.gguf':raise ValueError('情绪向量文件位置不受支持。')
        if hashlib.sha256(vector.read_bytes()).hexdigest()!=entry['sha256']:raise ValueError('情绪向量文件校验失败。')
        start,end=entry['layer_range']
        if not isinstance(start,int) or not isinstance(end,int) or not 1<=start<=end<=manifest['main_layers']:
            raise ValueError('情绪向量层范围无效。')
        item=components.setdefault(entry['sha256'],{'mode':mode,'file':str(vector),
            'argument_file':os.path.relpath(vector,runtime),'sha256':entry['sha256'],'layer_range':[start,end],'strength':0})
        item['strength']=round(item['strength']+strength,10)
    values=[components[k] for k in sorted(components) if components[k]['strength']]
    if not values:return {'mode':'off','signature':None,'components':[]}
    if len({tuple(v['layer_range']) for v in values})!=1:raise ValueError('混合向量的层范围不同，未加载。')
    signatures=[[v['sha256'],v['strength'],*v['layer_range']] for v in values]
    # Preserve the v27 signature for an unchanged single channel; order does not matter for sums.
    signature=hashlib.sha256(json.dumps(signatures[0] if len(values)==1 else signatures).encode()).hexdigest()
    return {**values[0],'mode':values[0]['mode'] if len(values)==1 else 'mixed',
        'signature':signature,'components':values}


def emotion_args(state):
    if state['mode']=='off':return []
    # This runtime uses FNAME:SCALE, unlike older releases' FNAME SCALE syntax.
    # The runtime's colon-separated parser rejects Windows drive letters. Its cwd is the backend directory.
    pieces=[]
    for item in state.get('components',[state]):
        filename=item.get('argument_file',item['file'])
        if ':' in filename or ',' in filename:raise ValueError('情绪向量命令行需使用后端目录下的普通相对路径。')
        pieces.append(filename+':'+str(item['strength']))
    return ['--control-vector-scaled',','.join(pieces),
            '--control-vector-layer-range',*[str(x) for x in state['layer_range']]]
