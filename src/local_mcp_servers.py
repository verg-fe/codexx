"""Small local MCP services for the model registry, design apps and the owned Android device."""
from __future__ import annotations

import hashlib
import base64
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

ROOT = Path(os.environ.get('LOCAL_CODEX_ROOT', r'D:\LocalCodex'))
ADB = Path(os.environ.get('LOCAL_CODEX_ADB', r'C:\Users\18213\AppData\Local\VectorAndroidSdk\platform-tools\adb.exe'))
DEVICE = os.environ.get('LOCAL_CODEX_ANDROID_SERIAL', '7lv4skzli7aaeipb')
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
_download_lock = threading.Lock()
_download_jobs: dict[str, dict] = {}


def _json(value):
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def _request(url, timeout=20):
    request = urllib.request.Request(url, headers={'User-Agent': 'MyCodex-local-model-manager/1.0', 'Accept': 'application/json'})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode('utf-8'))


def _valid_repo(repo_id):
    return isinstance(repo_id, str) and bool(re.fullmatch(r'[A-Za-z0-9_.-]{1,96}/[A-Za-z0-9_.-]{1,96}', repo_id))


def _catalog():
    from model_catalog import ModelCatalog
    try:
        from core import load_settings, model_directory
        directory=model_directory(load_settings())
    except (ImportError, OSError, ValueError):
        directory=Path(os.environ.get('LOCAL_CODEX_MODELS', r'G:\LocalCodex\models'))
    return ModelCatalog(ROOT, directory)


def _model_search(query, limit=20):
    if not query.strip():
        raise ValueError('请给出模型名称或架构关键词。')
    limit = max(1, min(int(limit), 30))
    url = 'https://huggingface.co/api/models?' + urllib.parse.urlencode({
        'search': query.strip(), 'pipeline_tag': 'text-generation', 'sort': 'downloads', 'direction': '-1', 'limit': limit,
    })
    rows = _request(url)
    result = []
    for row in rows:
        result.append({'repo_id': row.get('id'), 'revision': row.get('sha'), 'downloads': row.get('downloads'),
                       'likes': row.get('likes'), 'gated': row.get('gated'), 'private': row.get('private'),
                       'disabled': row.get('disabled'), 'pipeline_tag': row.get('pipeline_tag'),
                       'library_name': row.get('library_name'), 'last_modified': row.get('lastModified')})
    return {'query': query, 'source': 'Hugging Face Hub public model API', 'models': result}


def _model_inspect(repo_id, revision=None):
    if not _valid_repo(repo_id):
        raise ValueError('仓库必须是可信 Hub 的 owner/name 格式。')
    if revision and not re.fullmatch(r'[0-9a-fA-F]{40}', revision):
        raise ValueError('请传入搜索结果里的完整 40 位提交 SHA。')
    query = urllib.parse.urlencode({'blobs': 'true', **({'revision': revision} if revision else {})})
    row = _request('https://huggingface.co/api/models/' + urllib.parse.quote(repo_id, safe='/') + '?' + query)
    files = []
    for item in row.get('siblings', []):
        lfs = item.get('lfs') or {}
        name = item.get('rfilename', '')
        files.append({'filename': name, 'size_bytes': item.get('size'),
                      'sha256': lfs.get('sha256') or (lfs.get('oid', '').removeprefix('sha256:') or None),
                      'downloadable_model_file': name.lower().endswith('.gguf')})
    return {'repo_id': row.get('id'), 'revision': row.get('sha'), 'gated': row.get('gated'),
            'private': row.get('private'), 'disabled': row.get('disabled'), 'pipeline_tag': row.get('pipeline_tag'),
            'card_data': row.get('cardData'), 'files': files}


def _persist_download(job):
    folder = ROOT / 'logs' / 'model-downloads'
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (job['id'] + '.json')
    temp = path.with_suffix('.tmp')
    temp.write_text(_json(job), encoding='utf-8')
    os.replace(temp, path)


def _download_worker(job_id, repo_id, revision, filename, directory):
    with _download_lock:
        job = _download_jobs[job_id]
    try:
        if not _valid_repo(repo_id) or not re.fullmatch(r'[0-9a-fA-F]{40}', revision or ''):
            raise ValueError('下载必须绑定 Hub 返回的完整提交 SHA。')
        if Path(filename).name != filename or not filename.lower().endswith('.gguf'):
            raise ValueError('当前模型管理器只允许下载单个顶层 GGUF 文件。')
        info = _model_inspect(repo_id, revision)
        if info.get('revision', '').lower() != revision.lower():
            raise ValueError('仓库当前 revision 与用户选择的固定提交不一致。')
        if info.get('gated') or info.get('private') or info.get('disabled'):
            raise ValueError('此仓库受限、私有或已停用；当前流程不会尝试绕过访问控制。')
        source = next((item for item in info['files'] if item['filename'] == filename), None)
        if not source:
            raise ValueError('该文件不在已核对的仓库 revision 中。')
        expected_sha = source.get('sha256')
        expected_size = source.get('size_bytes')
        if not expected_sha or not re.fullmatch(r'[0-9a-fA-F]{64}', expected_sha):
            raise ValueError('Hub 未提供可验证的 SHA256；拒绝下载并登记权重。')
        dest_dir = Path(directory).expanduser().resolve()
        dest_dir.mkdir(parents=True, exist_ok=True)
        out_name = f"{repo_id.replace('/', '--')}--{Path(filename).name}"
        final_path = dest_dir / out_name
        partial = final_path.with_suffix(final_path.suffix + '.partial')
        url = 'https://huggingface.co/' + urllib.parse.quote(repo_id, safe='/') + '/resolve/' + revision + '/' + urllib.parse.quote(filename, safe='/')
        offset = partial.stat().st_size if partial.exists() else 0
        headers = {'User-Agent': 'MyCodex-local-model-manager/1.0'}
        if offset:
            headers['Range'] = f'bytes={offset}-'
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=90) as response:
            append = offset > 0 and response.status == 206
            if not append:
                offset = 0
            job.update(status='downloading', bytes=offset, total=expected_size, target=str(final_path),
                       source=repo_id, revision=revision, expected_sha256=expected_sha)
            _persist_download(job)
            mode = 'ab' if append else 'wb'
            with partial.open(mode) as out:
                while True:
                    if job.get('cancel_requested'):
                        job['status'] = 'cancelled'; job['updated_at'] = time.time(); _persist_download(job)
                        return
                    block = response.read(8 * 1024 * 1024)
                    if not block:
                        break
                    out.write(block)
                    job['bytes'] += len(block)
                    if job['bytes'] % (64 * 1024 * 1024) < len(block):
                        job['updated_at'] = time.time(); _persist_download(job)
        actual_size = partial.stat().st_size
        if expected_size is not None and actual_size != int(expected_size):
            raise ValueError(f'下载文件大小不符：预期 {expected_size}，实际 {actual_size}。')
        digest = hashlib.sha256()
        with partial.open('rb') as source_file:
            for block in iter(lambda: source_file.read(8 * 1024 * 1024), b''):
                digest.update(block)
        actual_sha = digest.hexdigest()
        if actual_sha.lower() != expected_sha.lower():
            raise ValueError(f'下载 SHA256 不匹配：Hub={expected_sha}，本地={actual_sha}。')
        os.replace(partial, final_path)
        job.update(status='downloaded_hash_verified', bytes=actual_size, sha256=actual_sha,
                   target=str(final_path), updated_at=time.time(), registration_required=True)
        _persist_download(job)
    except Exception as error:
        job.update(status='failed', error=f'{type(error).__name__}: {error}', updated_at=time.time())
        _persist_download(job)


def _download_start(repo_id, revision, filename):
    model_dir = Path(os.environ.get('LOCAL_CODEX_MODELS', r'G:\LocalCodex\models'))
    job_id = uuid.uuid4().hex[:12]
    job = {'id': job_id, 'status': 'queued', 'repo_id': repo_id, 'revision': revision,
           'filename': filename, 'bytes': 0, 'total': None, 'created_at': time.time(), 'updated_at': time.time()}
    with _download_lock:
        _download_jobs[job_id] = job
    _persist_download(job)
    threading.Thread(target=_download_worker, args=(job_id, repo_id, revision, filename, model_dir), daemon=True).start()
    return {'job_id': job_id, 'status': 'queued', 'message': '后台开始下载；不会自动注册或切换模型。'}


def _download_status(job_id):
    with _download_lock:
        job = _download_jobs.get(job_id)
    if job:
        return dict(job)
    path = ROOT / 'logs' / 'model-downloads' / (str(job_id) + '.json')
    if path.is_file():
        return json.loads(path.read_text(encoding='utf-8'))
    raise ValueError('找不到该下载任务。')


def _download_cancel(job_id):
    with _download_lock:
        job = _download_jobs.get(job_id)
        if not job:
            raise ValueError('找不到该下载任务。')
        if job['status'] not in ('queued', 'downloading'):
            return dict(job)
        job['cancel_requested'] = True
        job['updated_at'] = time.time()
        _persist_download(job)
        return {'job_id': job_id, 'status': job['status'], 'cancel_requested': True,
                'message': '已请求取消；保留 .partial 文件供后续断点续传。'}


def _model_register(path, display_name='', projector_path=''):
    record = _catalog().register_local(path, display_name or None, projector_path or None)
    return {'registered': True, 'model': record, 'runtime_validation_required': True}


def _model_validate(model_id, hash_file=False):
    result = _catalog().validate_local(model_id, hash_file=hash_file)
    runtime = {'active': False, 'health': None, 'model_path': None}
    try:
        from core import active_model, api, model_file
        live = active_model()
        props = api('/props', timeout=3)
        active_path = str(Path(props.get('model_path', '')).resolve()) if props.get('model_path') else None
        wanted_path = str(model_file(model_id).resolve())
        runtime = {'active': active_path == wanted_path, 'health': api('/health', timeout=3).get('status'),
                   'model_path': active_path}
        if runtime['active'] and runtime['health'] == 'ok' and live.get('model') == model_id:
            catalog = _catalog(); data = json.loads(catalog.path.read_text(encoding='utf-8-sig'))
            for row in data['models']:
                if row.get('id') == model_id:
                    row['status'] = 'runtime_validated'
                    row['last_runtime_validation_utc'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
            catalog.write(data)
            result['status'] = 'runtime_validated'
    except (OSError, ValueError, KeyError, urllib.error.URLError):
        pass
    return {**result, 'runtime_validation': 'passed' if result.get('status')=='runtime_validated' else 'pending',
            'active_runtime_check': runtime,
            'message': '文件检查已完成；只有该模型当前已在运行且 /health 与 /props 对上时才更新为运行时已验证。其余情况需先在桌面应用并验证模型。'}


def _model_activate(model_id):
    catalog = _catalog()
    validation = catalog.validate_local(model_id)
    if catalog[model_id].get('status') not in ('runtime_validated', 'builtin'):
        raise ValueError('该模型尚未通过实际运行时验证；当前仅登记/文件校验通过，拒绝自动切换。')
    request = {'request_id': uuid.uuid4().hex, 'model_id': model_id, 'status': 'queued', 'created_at': time.time(),
               'file_validation': validation}
    path = ROOT / 'model-activation-request.json'
    if path.is_file():
        try:
            old = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            old = {}
        if old.get('status') in ('queued', 'processing'):
            raise ValueError('已有模型切换请求排队中；请先检查其状态。')
    temp = path.with_suffix('.tmp')
    temp.write_text(_json(request), encoding='utf-8')
    os.replace(temp, path)
    return {'request_id': request['request_id'], 'status': 'queued',
            'message': '切换请求已入队；桌面客户端会等当前请求结束后处理。'}


def _adb(*args, timeout=25):
    if not ADB.is_file():
        raise FileNotFoundError(f'指定 ADB 不存在：{ADB}')
    result = subprocess.run([str(ADB), '-s', DEVICE, *map(str, args)], capture_output=True,
                            timeout=timeout, creationflags=NO_WINDOW)
    return result.returncode, (result.stdout + result.stderr).decode('utf-8', errors='replace').strip()


def _device_list():
    if not ADB.is_file():
        raise FileNotFoundError(f'指定 ADB 不存在：{ADB}')
    result = subprocess.run([str(ADB), 'devices', '-l'], capture_output=True, timeout=15, creationflags=NO_WINDOW)
    lines = (result.stdout + result.stderr).decode('utf-8', errors='replace').splitlines()
    devices = []
    for line in lines[1:]:
        match = re.match(r'^(\S+)\s+(device|unauthorized|offline)\b(.*)$', line.strip())
        if match:
            devices.append({'serial': match.group(1), 'state': match.group(2), 'details': match.group(3).strip()})
    return {'expected_serial': DEVICE, 'adb_exit_code': result.returncode, 'devices': devices,
            'expected_device_connected': any(row['serial'] == DEVICE and row['state'] == 'device' for row in devices)}


def _require_device():
    devices = _device_list()
    if not devices['expected_device_connected']:
        raise RuntimeError(f'指定设备 {DEVICE} 未处于 device 状态；不会对其他设备执行操作。设备列表：{devices["devices"]}')


def _device_info():
    _require_device()
    props = ('ro.product.manufacturer', 'ro.product.model', 'ro.product.device', 'ro.build.version.release',
             'ro.build.version.sdk', 'ro.product.cpu.abi', 'ro.build.fingerprint')
    code, output = _adb('shell', 'getprop', timeout=15)
    if code:
        raise RuntimeError(f'读取 getprop 失败 ({code})：{output}')
    values = [line.strip().strip('[]') for line in output.splitlines() if line.strip()]
    try:
        _, packages = _adb('shell', 'pm', 'list', 'packages', 'com.google.android.gms')
        _, store = _adb('shell', 'pm', 'list', 'packages', 'com.android.vending')
    except Exception:
        packages = store = ''
    relevant = {}
    for prop in props:
        code, text = _adb('shell', 'getprop', prop, timeout=10)
        relevant[prop] = text if code == 0 else None
    return {'serial': DEVICE, 'properties': relevant,
            'google_play_services_installed': 'com.google.android.gms' in packages,
            'play_store_installed': 'com.android.vending' in store}


def _packages_list(prefix=''):
    _require_device()
    code, output = _adb('shell', 'pm', 'list', 'packages', '-3', timeout=30)
    if code:
        raise RuntimeError(f'查询应用失败 ({code})：{output}')
    packages = sorted(line.removeprefix('package:') for line in output.splitlines() if line.startswith('package:'))
    if prefix:
        packages = [name for name in packages if name.lower().startswith(prefix.lower())]
    return {'serial': DEVICE, 'third_party_packages': packages, 'count': len(packages)}


def _find_apksigner():
    sdk = Path(os.environ.get('ANDROID_SDK_ROOT') or os.environ.get('ANDROID_HOME') or r'C:\Users\18213\AppData\Local\VectorAndroidSdk')
    candidates = sorted((sdk / 'build-tools').glob('*/apksigner.bat'), reverse=True)
    candidates += sorted((sdk / 'build-tools').glob('*/apksigner.exe'), reverse=True)
    if not candidates:
        raise FileNotFoundError(f'Android SDK build-tools 下找不到 apksigner：{sdk / "build-tools"}')
    return candidates[0]


def _apk_metadata(apk_path):
    path = Path(apk_path).expanduser().resolve(strict=True)
    if path.suffix.lower() != '.apk' or path.stat().st_size < 4096:
        raise ValueError('文件不是有效大小的 APK。')
    signer = _find_apksigner()
    result = subprocess.run([str(signer), 'verify', '--print-certs', str(path)], capture_output=True,
                            timeout=45, creationflags=NO_WINDOW)
    signing = (result.stdout + result.stderr).decode('utf-8', errors='replace')
    if result.returncode:
        raise ValueError(f'apksigner verify 失败 ({result.returncode})：{signing[:3000]}')
    cert = re.search(r'(?i)certificate SHA-256 digest:\s*([0-9a-f:]{64,95})', signing)
    cert_digest = cert.group(1).replace(':', '').lower() if cert else None
    application_id = None
    sdk = Path(os.environ.get('ANDROID_SDK_ROOT') or os.environ.get('ANDROID_HOME') or r'C:\Users\18213\AppData\Local\VectorAndroidSdk')
    analyzers = sorted(sdk.glob('cmdline-tools/*/bin/apkanalyzer.bat'), reverse=True)
    if analyzers:
        parsed = subprocess.run([str(analyzers[0]), 'manifest', 'application-id', str(path)], capture_output=True,
                                 timeout=25, creationflags=NO_WINDOW)
        if parsed.returncode == 0:
            application_id = parsed.stdout.decode('utf-8', errors='replace').strip()
    return {'path': str(path), 'size_bytes': path.stat().st_size, 'signature_verified': True,
            'certificate_sha256': cert_digest, 'package_name': application_id,
            'version': None, 'publisher_identity_confirmed': False}


def _install_apks(paths, package_name, expected_certificate_sha256, replace=False):
    _require_device()
    if not package_name or not re.fullmatch(r'[A-Za-z0-9_.]+', package_name):
        raise ValueError('必须给出有效的预期包名。')
    expected = re.sub(r'[^0-9a-f]', '', str(expected_certificate_sha256).lower())
    if not re.fullmatch(r'[0-9a-f]{64}', expected):
        raise ValueError('安装前必须提供 64 位可信签名证书 SHA256。')
    if not isinstance(paths, list) or not paths:
        raise ValueError('至少提供一个 APK；多文件时使用兼容的 split APK 集合。')
    verified = []
    for item in paths:
        meta = _apk_metadata(item)
        if meta['package_name'] and meta['package_name'] != package_name:
            raise ValueError(f"APK 包名不符：{meta['path']} 包含 {meta['package_name']}，预期 {package_name}。")
        if meta['certificate_sha256'] != expected:
            raise ValueError(f"APK 签名证书不符：{meta['path']} SHA256={meta['certificate_sha256']}，预期={expected}。")
        verified.append(meta)
    args = ['install', '-r'] if len(verified) == 1 else ['install-multiple', '-r']
    if replace:
        args.append('-d')
    args.extend(item['path'] for item in verified)
    code, output = _adb(*args, timeout=300)
    if code or 'Success' not in output:
        raise RuntimeError(f'ADB 安装失败 ({code})：{output}')
    check_code, package_path = _adb('shell', 'pm', 'path', package_name, timeout=20)
    if check_code or 'package:' not in package_path:
        raise RuntimeError('ADB 回报安装成功，但设备包管理器查不到目标包：' + package_path)
    return {'serial': DEVICE, 'package_name': package_name, 'installed': True, 'adb_result': output,
            'package_path': package_path, 'apk_signatures_checked': verified, 'launched': False}


def _launch_package(package_name):
    _require_device()
    if not re.fullmatch(r'[A-Za-z0-9_.]+', package_name or ''):
        raise ValueError('包名无效。')
    code, path = _adb('shell', 'pm', 'path', package_name)
    if code or 'package:' not in path:
        raise FileNotFoundError(f'设备上未安装 {package_name}。')
    code, output = _adb('shell', 'monkey', '-p', package_name, '1', timeout=30)
    return {'serial': DEVICE, 'package_name': package_name, 'launch_exit_code': code,
            'result': output, 'launched': code == 0 and 'No activities found' not in output}


def _screenshot(destination=''):
    _require_device()
    target = Path(destination).expanduser() if destination else ROOT / 'logs' / 'android' / f'screen-{int(time.time())}.png'
    target.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run([str(ADB), '-s', DEVICE, 'exec-out', 'screencap', '-p'], capture_output=True,
                            timeout=30, creationflags=NO_WINDOW)
    if result.returncode or not result.stdout.startswith(b'\x89PNG\r\n\x1a\n'):
        raise RuntimeError(f'设备截图不是有效 PNG (exit={result.returncode})：{result.stderr.decode("utf-8",errors="replace")[:500]}')
    target.write_bytes(result.stdout)
    return {'serial': DEVICE, 'path': str(target.resolve()), 'bytes': len(result.stdout), 'png_valid': True}


def _accessibility_tree():
    _require_device()
    code, output = _adb('shell', 'uiautomator', 'dump', '/sdcard/window.xml', timeout=40)
    if code:
        raise RuntimeError(f'无障碍树导出失败 ({code})：{output}')
    code, xml = _adb('shell', 'cat', '/sdcard/window.xml', timeout=15)
    if code or '<hierarchy' not in xml:
        raise RuntimeError('设备返回的无障碍树 XML 不完整：' + xml[:500])
    return {'serial': DEVICE, 'xml': xml[:80000], 'truncated': len(xml) > 80000}


def _logcat(package_name='', lines=300):
    _require_device()
    lines = max(20, min(int(lines), 1000))
    args = ['shell', 'pidof', package_name] if package_name else None
    pid = None
    if args:
        code, result = _adb(*args, timeout=10)
        if code == 0 and result.strip().isdigit():
            pid = result.strip()
    adb_args = ['logcat', '-d', '-t', str(lines)]
    if pid:
        adb_args.extend(['--pid', pid])
    code, output = _adb(*adb_args, timeout=30)
    if code:
        raise RuntimeError(f'logcat 读取失败 ({code})：{output[:1000]}')
    return {'serial': DEVICE, 'package_name': package_name or None, 'pid_filter': pid,
            'lines': output.splitlines()[-lines:], 'truncated': False}


def _port_open(port):
    try:
        with socket.create_connection(('127.0.0.1', int(port)), timeout=0.5):
            return True
    except OSError:
        return False


def _load_design_apps():
    path = ROOT / 'design-apps.json'
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return {}


def _write_json_atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(_json(data), encoding='utf-8')
    os.replace(temp, path)


def _write_design_processes(data):
    _write_json_atomic(ROOT / 'logs' / 'design-app-processes.json', data)


def _configure_freecad_local_autostart(app):
    settings_path = Path(app.get('settings_path', '')).resolve() if app.get('settings_path') else None
    appdata_root = (Path(os.environ.get('APPDATA', str(Path.home() / 'AppData' / 'Roaming'))) / 'FreeCAD').resolve()
    if not settings_path or not settings_path.is_relative_to(appdata_root):
        raise ValueError('FreeCAD MCP settings path must stay under the current user FreeCAD settings directory.')
    try:
        settings = json.loads(settings_path.read_text(encoding='utf-8')) if settings_path.is_file() else {}
    except (OSError, ValueError):
        settings = {}
    # The desktop MCP bridge is local-only. Preserve any existing auth token but
    # never enable a LAN listener as a side effect of launching the tool.
    settings.update({'remote_enabled': False, 'allowed_ips': '127.0.0.1', 'auto_start_rpc': True})
    settings.setdefault('auth_token', '')
    _write_json_atomic(settings_path, settings)


def _find_owned_design_pid(app, marker):
    if not marker:
        return None
    executable = Path(app.get('executable', '')).resolve()
    root = executable.parent
    def ps(value):
        return "'" + str(value).replace("'", "''") + "'"
    script = (
        f"$root={ps(root)}; $marker={ps(marker)}; "
        "$rows=Get-CimInstance Win32_Process | Where-Object { "
        "$_.Name -in @('freecad.exe','blender.exe') -and $_.ExecutablePath -and "
        "$_.ExecutablePath.StartsWith($root,[StringComparison]::OrdinalIgnoreCase) -and "
        "$_.CommandLine.Contains($marker) } | Sort-Object CreationDate; "
        "@($rows | ForEach-Object { [int]$_.ProcessId }) | ConvertTo-Json -Compress"
    )
    encoded = base64.b64encode(script.encode('utf-16le')).decode('ascii')
    try:
        result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded],
                                capture_output=True, text=True, timeout=10, creationflags=NO_WINDOW)
        values = json.loads(result.stdout) if result.stdout.strip() else []
        if isinstance(values, int):
            return values
        return int(values[-1]) if values else None
    except (OSError, subprocess.TimeoutExpired, ValueError, TypeError, IndexError):
        return None


def _design_status():
    config = _load_design_apps()
    state_path = ROOT / 'logs' / 'design-app-processes.json'
    try:
        owned = json.loads(state_path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        owned = {}
    statuses = {}
    for key, app in config.items():
        port = app.get('port', 9876 if key == 'blender' else 9875)
        pid = (owned.get(key) or {}).get('pid')
        alive = False
        if isinstance(pid, int):
            try:
                listing=subprocess.run(['tasklist', '/FI', f'PID eq {pid}', '/FO', 'CSV', '/NH'], capture_output=True,
                                       timeout=5, creationflags=NO_WINDOW).stdout.decode('utf-8', errors='replace')
                alive = any(len(cols)>1 and cols[1].strip().strip('"')==str(pid)
                            for cols in (line.split(',') for line in listing.splitlines()))
            except OSError:
                pass
        statuses[key] = {'path': app.get('executable'), 'version': app.get('version'), 'owned_pid': pid,
                         'owned_process_alive': alive, 'rpc_port': port, 'rpc_listening': _port_open(port)}
    return {'apps': statuses, 'jobs_root': str(ROOT / 'design-jobs')}


def _start_design_app(name, job_dir=''):
    config = _load_design_apps()
    app = config.get(name) or {}
    executable = Path(app.get('executable', '')).resolve() if app.get('executable') else None
    if not executable or not executable.is_file():
        raise FileNotFoundError(f'{name} 程序路径尚未配置或不存在，请运行本工作台的设计工具部署器。')
    status = _design_status()['apps'].get(name, {})
    if status.get('rpc_listening'):
        return {'app': name, 'already_running': True, 'status': status}
    working = ROOT / 'design-jobs' / ('current' if not job_dir else Path(job_dir).name)
    working.mkdir(parents=True, exist_ok=True)
    args = [str(executable)]
    if app.get('startup_script') and Path(app['startup_script']).is_file():
        args += ['--python', app['startup_script']]
    if name == 'freecad':
        _configure_freecad_local_autostart(app)
        if app.get('startup_macro') and Path(app['startup_macro']).is_file():
            args.append(app['startup_macro'])
    env = dict(os.environ)
    env.update({'DISABLE_TELEMETRY': 'true', 'BLENDERMCP_ADDONS_DIR': app.get('blender_addons_dir', '')})
    env['LOCAL_CODEX_DESIGN_JOB_DIR'] = str(working)
    state_path = ROOT / 'logs' / 'design-app-processes.json'
    state_path.parent.mkdir(parents=True, exist_ok=True)
    log_path = ROOT / 'logs' / f'{name}-startup.log'
    with log_path.open('wb', buffering=0) as log_file:
        process = subprocess.Popen(args, cwd=str(working), env=env, stdin=subprocess.DEVNULL,
                                   stdout=log_file, stderr=subprocess.STDOUT,
                                   creationflags=getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0))
    marker = app.get('startup_script') if name == 'blender' else app.get('startup_macro') if name == 'freecad' else ''
    managed_pid = None
    if marker:
        for _ in range(10):
            managed_pid = _find_owned_design_pid(app, marker)
            if managed_pid:
                break
            time.sleep(0.25)
    managed_pid = managed_pid or process.pid
    try:
        owned = json.loads(state_path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        owned = {}
    owned[name] = {'pid': managed_pid, 'launcher_pid': process.pid, 'started_at': time.time(),
                   'job_dir': str(working), 'startup_log': str(log_path)}
    _write_design_processes(owned)
    return {'app': name, 'pid': managed_pid, 'launcher_pid': process.pid, 'job_dir': str(working),
            'startup_log': str(log_path), 'status': 'starting',
            'message': '已启动图形程序；status 可检查 MCP RPC 连接，启动日志保存在该路径。'}


def _stop_design_app(name):
    state_path = ROOT / 'logs' / 'design-app-processes.json'
    try:
        owned = json.loads(state_path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        owned = {}
    item = owned.get(name)
    if not item or not isinstance(item.get('pid'), int):
        return {'app': name, 'stopped': False, 'reason': '没有该工作台记录的受管进程；不会关闭其他来源的应用。'}
    pid = item['pid']
    code = subprocess.run(['taskkill', '/PID', str(pid), '/T', '/F'], capture_output=True,
                          timeout=20, creationflags=NO_WINDOW).returncode
    if code == 0:
        owned.pop(name, None)
        _write_design_processes(owned)
    return {'app': name, 'pid': pid, 'stopped': code == 0, 'taskkill_exit_code': code}


def _schemas():
    return {
        'model-manager': [
            ('model_list', '列出内置和本地注册的 GGUF 模型。', {'type':'object','properties':{}}),
            ('model_search', '搜索真实公开发布的 Hugging Face 文本生成模型。', {'type':'object','properties':{'query':{'type':'string'},'limit':{'type':'integer','default':20}},'required':['query']}),
            ('model_inspect', '读取模型卡、提交 SHA、可用 GGUF 文件与可信哈希。', {'type':'object','properties':{'repo_id':{'type':'string'},'revision':{'type':'string'}},'required':['repo_id']}),
            ('model_download', '按不可变提交与 Hub SHA256 断点续传下载单个 GGUF；不会自动切换。', {'type':'object','properties':{'repo_id':{'type':'string'},'revision':{'type':'string'},'filename':{'type':'string'}},'required':['repo_id','revision','filename']}),
            ('model_download_status', '查询下载进度。', {'type':'object','properties':{'job_id':{'type':'string'}},'required':['job_id']}),
            ('model_download_cancel', '请求取消下载并保留 partial 供断点续传。', {'type':'object','properties':{'job_id':{'type':'string'}},'required':['job_id']}),
            ('model_register', '将本地 GGUF 的已读元数据加入共享模型注册表；不代表运行通过。', {'type':'object','properties':{'path':{'type':'string'},'display_name':{'type':'string'},'projector_path':{'type':'string'}},'required':['path']}),
            ('model_validate', '核对本地模型路径/大小，可选择计算完整 SHA256。', {'type':'object','properties':{'model_id':{'type':'string'},'hash_file':{'type':'boolean','default':False}},'required':['model_id']}),
            ('model_activate', '将已通过运行时验证的模型排入安全切换队列。', {'type':'object','properties':{'model_id':{'type':'string'}},'required':['model_id']}),
            ('model_rollback', '排入切回上一成功模型的请求。', {'type':'object','properties':{}}),
        ],
        'android': [
            ('android_devices', '列出 ADB 设备；任何操作只允许指定序列号。', {'type':'object','properties':{}}),
            ('android_device_info', '读取指定设备的 ROM、Android、API、ABI 和 Google 组件状态。', {'type':'object','properties':{}}),
            ('android_packages', '列出设备上已安装的第三方包，可按前缀过滤。', {'type':'object','properties':{'prefix':{'type':'string','default':''}}}),
            ('android_apk_inspect', '读取 APK 包名并用 apksigner 验证签名。', {'type':'object','properties':{'apk_path':{'type':'string'}},'required':['apk_path']}),
            ('android_install_apks', '安装前必须匹配期望的包名及可信签名证书 SHA256；仅操作指定设备。', {'type':'object','properties':{'apk_paths':{'type':'array','items':{'type':'string'}},'package_name':{'type':'string'},'expected_certificate_sha256':{'type':'string'},'allow_downgrade':{'type':'boolean','default':False}},'required':['apk_paths','package_name','expected_certificate_sha256']}),
            ('android_launch', '启动已安装应用；登录/授权停留在用户操作界面。', {'type':'object','properties':{'package_name':{'type':'string'}},'required':['package_name']}),
            ('android_accessibility_tree', '导出设备当前 UIAutomator XML 无障碍树。', {'type':'object','properties':{}}),
            ('android_screenshot', '保存并验证真实二进制 PNG 设备截图。', {'type':'object','properties':{'destination':{'type':'string','default':''}}}),
            ('android_logcat', '读取最近设备日志；给出包名时按进程 PID 定向。', {'type':'object','properties':{'package_name':{'type':'string','default':''},'lines':{'type':'integer','default':300}}}),
        ],
        'design-control': [
            ('design_status', '查询 Blender/FreeCAD 受管进程、RPC 端口和任务目录。', {'type':'object','properties':{}}),
            ('blender_start', '按需启动受管 Blender 图形界面并等待 MCP 插件连接。', {'type':'object','properties':{'job_dir':{'type':'string','default':''}}}),
            ('blender_stop', '仅关闭本工作台自己启动并记录 PID 的 Blender 进程树。', {'type':'object','properties':{}}),
            ('freecad_start', '按需启动受管 FreeCAD 图形界面及 MCP 插件。', {'type':'object','properties':{'job_dir':{'type':'string','default':''}}}),
            ('freecad_stop', '仅关闭本工作台自己启动并记录 PID 的 FreeCAD 进程树。', {'type':'object','properties':{}}),
        ],
    }


def _dispatch(service, name, args):
    args = args if isinstance(args, dict) else {}
    if service == 'model-manager':
        if name == 'model_list': return {'models': [dict(row, id=model_id) for model_id, row in _catalog().items()]}
        if name == 'model_search': return _model_search(str(args.get('query','')), args.get('limit',20))
        if name == 'model_inspect': return _model_inspect(args['repo_id'], args.get('revision'))
        if name == 'model_download': return _download_start(args['repo_id'], args['revision'], args['filename'])
        if name == 'model_download_status': return _download_status(args['job_id'])
        if name == 'model_download_cancel': return _download_cancel(args['job_id'])
        if name == 'model_register': return _model_register(args['path'], args.get('display_name',''), args.get('projector_path',''))
        if name == 'model_validate': return _model_validate(args['model_id'], bool(args.get('hash_file',False)))
        if name == 'model_activate': return _model_activate(args['model_id'])
        if name == 'model_rollback':
            history = ROOT / 'model-activation-history.json'
            rows = json.loads(history.read_text(encoding='utf-8')) if history.exists() else []
            if len(rows) < 2: raise ValueError('还没有足够的成功切换记录用于回退。')
            return _model_activate(rows[-2]['model_id'])
    if service == 'android':
        if name == 'android_devices': return _device_list()
        if name == 'android_device_info': return _device_info()
        if name == 'android_packages': return _packages_list(args.get('prefix',''))
        if name == 'android_apk_inspect': return _apk_metadata(args['apk_path'])
        if name == 'android_install_apks': return _install_apks(args['apk_paths'], args['package_name'], args['expected_certificate_sha256'], bool(args.get('allow_downgrade',False)))
        if name == 'android_launch': return _launch_package(args['package_name'])
        if name == 'android_accessibility_tree': return _accessibility_tree()
        if name == 'android_screenshot': return _screenshot(args.get('destination',''))
        if name == 'android_logcat': return _logcat(args.get('package_name',''), args.get('lines',300))
    if service == 'design-control':
        if name == 'design_status': return _design_status()
        if name == 'blender_start': return _start_design_app('blender', args.get('job_dir',''))
        if name == 'blender_stop': return _stop_design_app('blender')
        if name == 'freecad_start': return _start_design_app('freecad', args.get('job_dir',''))
        if name == 'freecad_stop': return _stop_design_app('freecad')
    raise ValueError('未实现或不支持的工具：' + name)


def serve(service):
    schemas = _schemas().get(service)
    if not schemas:
        raise ValueError('MCP service name is not recognized.')
    tools = [{'name': name, 'description': description, 'inputSchema': schema} for name, description, schema in schemas]
    def reply(request, result=None, error=None):
        if 'id' not in request: return
        response = {'jsonrpc':'2.0','id':request['id']}
        response['error' if error else 'result'] = error or result
        sys.stdout.buffer.write(json.dumps(response,ensure_ascii=False).encode('utf-8')+b'\n')
        sys.stdout.buffer.flush()
    for raw in sys.stdin.buffer:
        try:
            request=json.loads(raw); method=request.get('method'); params=request.get('params') or {}
            if method=='initialize':
                reply(request,{'protocolVersion':params.get('protocolVersion','2024-11-05'),
                    'capabilities':{'tools':{'listChanged':False}},'serverInfo':{'name':'mycodex-'+service,'version':'53.0'}})
            elif method=='ping': reply(request,{})
            elif method=='tools/list': reply(request,{'tools':tools})
            elif method=='tools/call':
                try:
                    result=_dispatch(service,params['name'],params.get('arguments') or {})
                    reply(request,{'content':[{'type':'text','text':_json(result)}],'structuredContent':result,'isError':False})
                except Exception as error:
                    reply(request,{'content':[{'type':'text','text':f'{type(error).__name__}: {error}'}],'isError':True})
            elif 'id' in request: reply(request,error={'code':-32601,'message':'Method not found'})
        except (ValueError,KeyError,TypeError):
            continue


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit('usage: local_mcp_servers.py model-manager|android|design-control')
    serve(sys.argv[1])
