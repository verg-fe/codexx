"""MoE4All 0.9 integration. Never treat SSE chunks or characters as tokens."""
import json
from pathlib import Path
import re
import subprocess
import time

VERSION = '0.9.0'
DIRECTORY = 'runtime-moe4all/MoE4All-Windows-x86_64-v0.9.0'
CONTEXT_LIMIT = 262144


def validate(settings, name, context, template, emotion, decoding):
    if settings.get('moe_kv_mode') == 'ram':
        if context > 71680:
            raise ValueError('本机 RAM 辅助配置目前仅验证到 70K，请降低上下文。')
        if settings.get('moe_vision_enabled', True):
            raise ValueError('本机 RAM 辅助配置的视觉后端初始化失败，目前请选择纯文字。')
    if context > CONTEXT_LIMIT:
        raise ValueError('MoE4All 目前按原生 256K 上限接入；请将完整模式滑条调到 256K 以下。')
    if template.get('file'):
        raise ValueError('MoE4All 0.9 不支持外部模板。Jack 请选“Jack 原始 XML · 恢复”，其他模板继续使用 Vulkan/HIP。')
    if emotion.get('components'):
        raise ValueError('MoE4All 尚不支持本工作台的情绪向量，请关闭情绪向量或使用 Vulkan/HIP。')
    if decoding != 'none':
        raise ValueError('现有 Jack 的共享 MTP 方式与 MoE4All 不同；请先选择“常规输出”。')
    if settings.get('cpu_offload'):
        raise ValueError('MoE4All 使用 GPU 计算和自动分页，请关闭 CPU 模型层卸载。')


def arguments(root, executable, settings, weights, projector, context):
    root = Path(root)
    directory = root/'cache'
    directory.mkdir(parents=True, exist_ok=True)
    config = directory/'moe4all-server.toml'
    # u32::MAX removes the engine's default 2048/131072 output limits. EOS and
    # the actual context capacity still apply, as in the original server.
    text = ('[sampling]\ntemp = 1.0\ntop_k = 20\ntop_p = 0.95\n'
            'max_new = 4294967295\nno_think = false\npreserve_thinking = true\n'
            'reasoning_effort = "medium"\n'
            '[kv]\ntype_k = "q8_0"\ntype_v = "q8_0"\nslots = 1\n'
            'dynamic = true\noverflow = false\nring = false\n'
            '[serve]\napi_key = '+json.dumps(settings['api_key'])+'\n'
            'max_tokens_cap = 4294967295\nrequest_timeout_secs = 0\nstats_interval_secs = 1\n')
    ram_mode = settings.get('moe_kv_mode') == 'ram'
    if ram_mode:
        text = text.replace('dynamic = true\noverflow = false',
            'dynamic = false\noverflow = true\noverflow_vram_mb = 512')
    if settings.get('moe_ssd_cache', True) and not ram_mode:
        cache = Path(settings.get('moe_cache_directory', r'G:\LocalCodex\cache\moe4all'))
        cache.mkdir(parents=True, exist_ok=True)
        text = text.replace('[serve]', 'session_cache_dir = '+json.dumps(str(cache))+
            '\nsession_idle_secs = 120\nsession_cache_max = "5GiB"\nsession_cache_ttl_hours = 24\n[serve]')
    config.write_text(text, encoding='utf-8')
    result = [str(executable),'serve',str(weights),'--config',str(config),
              '--addr','127.0.0.1:8080','--dev','Vulkan0','--ctx',str(context),
              '--parallel','1','--threads','6','--think']
    if ram_mode:
        result += ['--ubatch', '16']
    if not settings.get('moe_vision_enabled', True):
        projector = None
    if projector is not None:
        result += ['--mmproj', str(projector)]
    return result


def resources(executable, cwd, environment, no_window):
    result = subprocess.run([str(executable),'resources'], cwd=cwd, env=environment,
        capture_output=True, timeout=20, creationflags=no_window)
    if result.returncode:
        raise RuntimeError('MoE4All 未能查询本机显存，请查看后端运行日志。')
    return json.loads(result.stdout)


def progress(log_file):
    """Bounded tail of the engine's exact model-token progress (one slot)."""
    try:
        with Path(log_file).open('rb') as stream:
            stream.seek(0, 2)
            stream.seek(max(0, stream.tell()-65536))
            lines = stream.read().decode('utf-8', errors='replace').splitlines()
    except OSError:
        return {}
    state = {}
    for line in lines:
        line = re.sub(r'\x1b\[[0-9;]*m', '', line)
        if not any(x in line for x in ('request start','request progress','request done')):
            continue
        values = {
            k: quoted or plain for k, quoted, plain in re.findall(r'(\w+)=(?:"([^"]*)"|([^\s]+))', line)}
        request = values.get('req')
        if request != state.get('request_id') or 'request start' in line:
            state = {'request_id':request,'generated_tokens':0,'is_processing':True}
        state['is_processing'] = 'request done' not in line
        for source, dest in [('gen_tokens','generated_tokens'),('decode_tps','average_tps'),
                             ('context_tokens','context_tokens'),('elapsed_ms','elapsed_ms'),
                             ('decode_ms','decode_ms'),
                             ('prefill_tokens','prefill_tokens'),('prefill_total','prefill_total'),
                             ('cached_tokens','cached_tokens')]:
            try:state[dest]=float(values[source])
            except (KeyError,ValueError):pass
        state['phase'] = values.get('phase', 'finished' if not state['is_processing'] else 'waiting')
    return state


def normalize_request(body, route):
    """Remove llama-specific hints only; retain meaningful user request fields."""
    body = dict(body)
    for key in ('reasoning_budget_tokens','thinking_budget_tokens','timings_per_token'):
        body.pop(key, None)
    # The native CLI requests high effort; this engine's Qwen tier is xhigh.
    if isinstance(body.get('reasoning'),dict):
        body['reasoning']=dict(body['reasoning'])
        if body['reasoning'].get('effort')=='high':body['reasoning']['effort']='xhigh'
    if route=='/v1/responses':
        body.pop('safety_identifier',None)
    return body
