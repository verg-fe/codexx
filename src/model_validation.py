"""Background isolated CPU probes with reproducible capability evidence."""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import socket
import struct
import subprocess
import threading
import time
import urllib.request
import uuid
import zlib

_jobs = {}
_lock = threading.Lock()
_resource_lock = threading.Lock()


def identity(path):
    p = Path(path).resolve(strict=True)
    stat = p.stat()
    return {'path': str(p), 'size_bytes': stat.st_size, 'mtime_ns': stat.st_mtime_ns}


def evidence_is_current(row, path):
    evidence = row.get('validation_evidence') or {}
    try:
        if row.get('status') != 'runtime_validated' or evidence.get('weight') != identity(path):
            return False
        if evidence.get('runtime') != identity(evidence['runtime']['path']):
            return False
        libraries = evidence.get('runtime_libraries', [])
        if any(item != identity(item['path']) for item in libraries):
            return False
        if row.get('vision'):
            if not evidence.get('projector') or evidence['projector'] != identity(evidence['projector']['path']):
                return False
        probes = evidence.get('probes') or {}
        required = ['chinese', 'tools'] if row.get('supports_tools') else ['chinese']
        if row.get('vision'): required.append('vision')
        return all(probes.get(key, {}).get('passed') is True for key in required)
    except (OSError, KeyError, TypeError):
        return False


def _json_http(base, endpoint, key, payload=None, timeout=300):
    request = urllib.request.Request(base + endpoint,
        data=json.dumps(payload, ensure_ascii=False).encode('utf-8') if payload is not None else None,
        headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=timeout) as response:
        return json.load(response)


def _red_image():
    def chunk(kind, value):
        return struct.pack('>I', len(value)) + kind + value + struct.pack('>I', zlib.crc32(kind + value) & 0xffffffff)
    png = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>2I5B', 64, 64, 8, 2, 0, 0, 0))
    png += chunk(b'IDAT', zlib.compress((b'\0' + b'\xff\0\0' * 64) * 64)) + chunk(b'IEND', b'')
    return 'data:image/png;base64,' + base64.b64encode(png).decode('ascii')


def capability_probes(request, row, check_cancel=lambda: None):
    probes = {}
    def chat(messages, **kw):
        check_cancel()
        payload = {'model': row['id'], 'messages': messages, 'max_tokens': 64, 'temperature': 0,
                   'chat_template_kwargs': {'enable_thinking': False}, **kw}
        response = request('/v1/chat/completions', payload)
        choices = response.get('choices') or []
        if not choices: raise RuntimeError('运行时未返回生成结果')
        return choices[0].get('message') or {}
    message = chat([{'role': 'user', 'content': '请只回答四个汉字：验证成功'}])
    text = message.get('content') or ''
    probes['chinese'] = {'passed': '验证成功' in text, 'output': text[:300]}
    if not probes['chinese']['passed']: raise RuntimeError('中文输出探测未通过：' + text[:160])
    if row.get('supports_tools'):
        tool = {'type': 'function', 'function': {'name': 'validation_echo', 'description': 'Return the specified value',
                'parameters': {'type': 'object', 'properties': {'value': {'type': 'string'}}, 'required': ['value']}}}
        message = chat([{'role': 'user', 'content': 'Call validation_echo with value exactly ok54.'}],
                       tools=[tool], tool_choice='required')
        calls = message.get('tool_calls') or []
        passed = False
        for call in calls:
            function = call.get('function') or {}
            try: arguments = json.loads(function.get('arguments', ''))
            except (ValueError, TypeError): continue
            passed |= function.get('name') == 'validation_echo' and arguments == {'value': 'ok54'}
        probes['tools'] = {'passed': passed, 'output': calls}
        if not passed: raise RuntimeError('原生工具名称或 JSON 参数验证失败')
    if row.get('vision'):
        message = chat([{'role': 'user', 'content': [
            {'type': 'text', 'text': '这张纯色图片是什么颜色？只回答颜色。'},
            {'type': 'image_url', 'image_url': {'url': _red_image()}}]}])
        text = message.get('content') or ''
        passed = '红' in text or 'red' in text.lower()
        probes['vision'] = {'passed': passed, 'output': text[:300]}
        if not passed: raise RuntimeError('视觉颜色探测未通过')
    return probes


def _persist(root, job):
    folder = Path(root) / 'logs' / 'model-validation'
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / (job['id'] + '.json')
    with _lock:
        temp = target.with_suffix('.tmp')
        temp.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding='utf-8')
        os.replace(temp, target)


def validation_status(root, job_id):
    if not re.fullmatch(r'[0-9a-f]{12}', job_id or ''): raise ValueError('无效验证任务 ID')
    with _lock:
        job = _jobs.get(job_id)
        if job: return dict(job)
    return json.loads((Path(root) / 'logs' / 'model-validation' / (job_id + '.json')).read_text(encoding='utf-8'))


def cancel_validation(root, job_id):
    job = validation_status(root, job_id)
    with _lock:
        live = _jobs.get(job_id)
        if not live and job['status'] not in ('passed', 'failed', 'cancelled'):
            raise ValueError('验证服务已结束；此任务不能继续，需重新验证。')
        if live and live['status'] not in ('passed', 'failed', 'cancelled'):
            live['cancel_requested'] = True
            job = dict(live)
    _persist(root, job)
    return job


def _worker(root, catalog, job, hash_file):
    process = None
    cancelled = threading.Event()
    def check():
        if job.get('cancel_requested'): raise InterruptedError('用户取消旁路验证')
    def monitor():
        while not cancelled.wait(.2):
            if job.get('cancel_requested') and process and process.poll() is None:
                process.terminate()  # Popen retains this particular process handle on Windows.
                return
    try:
        while not _resource_lock.acquire(timeout=.2): check()
        try:
            check()
            result = catalog.validate_local(job['model_id'], hash_file=hash_file)
            row = dict(catalog[job['model_id']])
            from core import available_ram_mib, runtime_executable, runtime_environment, vision_file
            runtime = runtime_executable('vulkan')
            if not runtime.is_file(): raise FileNotFoundError('旁路 llama-server 运行时尚未安装')
            if available_ram_mib() < result['size_bytes'] / 1048576 + 2048:
                raise RuntimeError('旁路 CPU 验证所需内存不足；未启动其他模型，当前模型保留')
            sock = socket.socket(); sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]; sock.close()
            key = secrets.token_hex(24)
            base = f'http://127.0.0.1:{port}'
            evidence = {'weight': identity(result['path']), 'runtime': identity(runtime), 'context': 8192,
                        'backend': 'CPU isolated', 'projector': None,
                        'runtime_libraries': [identity(p) for p in sorted(runtime.parent.glob('*.dll'))]}
            args = [str(runtime), '-m', result['path'], '--host', '127.0.0.1', '--port', str(port),
                    '--api-key', key, '-c', '8192', '-np', '1', '-ngl', '0', '-t', '4', '-b', '256',
                    '--jinja', '--no-webui', '-fa', 'on', '-ctk', 'q4_0', '-ctv', 'q4_0']
            if row.get('vision'):
                projector = vision_file(name=row['id'])
                evidence['projector'] = identity(projector)
                args += ['--mmproj', str(projector), '--no-mmproj-offload']
            folder = Path(root) / 'logs' / 'model-validation'
            folder.mkdir(parents=True, exist_ok=True)
            logfile = folder / (job['id'] + '.log')
            with logfile.open('wb') as log:
                process = subprocess.Popen(args, cwd=runtime.parent, env=runtime_environment('vulkan'),
                    stdin=subprocess.DEVNULL, stdout=log, stderr=log, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            job.update(status='loading', pid=process.pid, port=port, log=str(logfile))
            _persist(root, job)
            threading.Thread(target=monitor, daemon=True).start()
            deadline = time.monotonic() + 300
            while time.monotonic() < deadline:
                check()
                if process.poll() is not None: raise RuntimeError('旁路模型加载退出，请查看验证日志')
                try:
                    if _json_http(base, '/health', key, timeout=2).get('status') == 'ok': break
                except (OSError, ValueError): pass
                time.sleep(.5)
            else: raise TimeoutError('旁路加载验证超过 300 秒，当前生产模型未切换')
            props = _json_http(base, '/props', key)
            if Path(props.get('model_path', '')).resolve() != Path(result['path']).resolve():
                raise RuntimeError('旁路实例实际模型路径不匹配')
            job['status'] = 'probing'; _persist(root, job)
            evidence['probes'] = capability_probes(lambda endpoint, payload: _json_http(base, endpoint, key, payload), row, check)
            check()
            if evidence['weight'] != identity(result['path']): raise RuntimeError('验证期间权重发生变化')
            evidence['validated_at'] = time.time()
            data = json.loads(catalog.path.read_text(encoding='utf-8-sig'))
            for current in data['models']:
                if current.get('id') == row['id']:
                    current.update(status='runtime_validated', validation_evidence=evidence)
            catalog.write(data)
            job.update(status='passed', evidence=evidence)
        finally:
            _resource_lock.release()
    except Exception as error:
        job.update(status='cancelled' if job.get('cancel_requested') else 'failed', error=f'{type(error).__name__}: {error}')
    finally:
        cancelled.set()
        if process and process.poll() is None:
            process.terminate()
            try: process.wait(timeout=10)
            except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=5)
        job['finished_at'] = time.time()
        _persist(root, job)


def start_validation(root, catalog, model_id, hash_file=False):
    catalog[model_id]  # Fail before queueing invalid IDs.
    with _lock:
        existing = next((j for j in _jobs.values() if j['status'] not in ('passed','failed','cancelled')), None)
        if existing: return dict(existing)
        job = {'id': uuid.uuid4().hex[:12], 'model_id': model_id, 'status': 'queued', 'created_at': time.time()}
        _jobs[job['id']] = job
    _persist(root, job)
    threading.Thread(target=_worker, args=(root, catalog, job, hash_file), daemon=True).start()
    return dict(job)


def probe_current_runtime(model_id):
    from core import api, MODELS, model_file, load_settings
    settings = load_settings()
    base = 'http://127.0.0.1:8080'
    props = api('/props', timeout=3)
    if Path(props.get('model_path','')).resolve() != model_file(model_id).resolve():
        raise RuntimeError('切换后模型路径与选择不符')
    return capability_probes(lambda endpoint, payload: _json_http(base, endpoint, settings['api_key'], payload), MODELS[model_id])
