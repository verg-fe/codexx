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
import zipfile
import android_coordinates

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
    endpoint = 'https://huggingface.co/api/models/' + urllib.parse.quote(repo_id, safe='/')
    if revision:
        endpoint += '/revision/' + urllib.parse.quote(revision, safe='')
    row = _request(endpoint + '?blobs=true')
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
    from model_validation import start_validation
    return start_validation(ROOT, _catalog(), model_id, hash_file)


def _model_activate(model_id):
    catalog = _catalog()
    validation = catalog.validate_local(model_id)
    from model_validation import evidence_is_current
    if catalog[model_id].get('status') != 'builtin' and not evidence_is_current(catalog[model_id], validation['path']):
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
    application_label = None
    application_labels = []
    version_code = min_sdk = None
    sdk = Path(os.environ.get('ANDROID_SDK_ROOT') or os.environ.get('ANDROID_HOME') or r'C:\Users\18213\AppData\Local\VectorAndroidSdk')
    analyzers = sorted(sdk.glob('cmdline-tools/*/bin/apkanalyzer.bat'), reverse=True)
    if analyzers:
        parsed = subprocess.run([str(analyzers[0]), 'manifest', 'application-id', str(path)], capture_output=True,
                                 timeout=25, creationflags=NO_WINDOW)
        if parsed.returncode == 0:
            application_id = parsed.stdout.decode('utf-8', errors='replace').strip()
            for field, operation in (('min_sdk', 'min-sdk'), ('version_code', 'version-code')):
                metadata = subprocess.run([str(analyzers[0]), 'manifest', operation, str(path)], capture_output=True,
                                          timeout=25, creationflags=NO_WINDOW)
                value = metadata.stdout.decode('utf-8', errors='replace').strip()
                if metadata.returncode == 0 and value.isdigit():
                    if field == 'min_sdk': min_sdk = int(value)
                    else: version_code = int(value)
    aapt_tools = sorted((sdk / 'build-tools').glob('*/aapt2.exe'), reverse=True)
    if aapt_tools and (not application_id or min_sdk is None or version_code is None or application_label is None):
        badging = subprocess.run([str(aapt_tools[0]), 'dump', 'badging', str(path)], capture_output=True,
                                timeout=25, creationflags=NO_WINDOW)
        if badging.returncode == 0:
            badge = badging.stdout.decode('utf-8', errors='replace')
            package = re.search(r"(?m)^package: name='([^']+)' versionCode='(\d+)'", badge)
            sdk_match = re.search(r"(?m)^sdkVersion:'(\d+)'", badge)
            label_match = (re.search(r"(?m)^application-label:'([^']*)'", badge)
                           or re.search(r"(?m)^application:\s+label='([^']*)'", badge))
            application_labels = list(dict.fromkeys(re.findall(
                r"(?m)^application-label(?:-[^:]*)?:'([^']*)'", badge)))
            if package: application_id, version_code = package.group(1), int(package.group(2))
            if sdk_match: min_sdk = int(sdk_match.group(1))
            if label_match: application_label = label_match.group(1)
            if not application_label and application_labels:
                application_label = application_labels[0]
    with zipfile.ZipFile(path) as archive:
        abis = sorted({name.split('/')[1] for name in archive.namelist()
                       if name.startswith('lib/') and name.endswith('.so') and len(name.split('/')) > 2})
    return {'path': str(path), 'size_bytes': path.stat().st_size, 'signature_verified': True,
            'certificate_sha256': cert_digest, 'package_name': application_id,
            'application_label': application_label, 'application_labels': application_labels,
            'version_code': version_code, 'min_sdk': min_sdk, 'native_abis': abis,
            'publisher_identity_confirmed': False}


def _capture_install_prompt_screenshot():
    configured = os.environ.get('LOCAL_CODEX_ANDROID_INSTALL_PROMPT_CAPTURE', '').strip()
    if not configured:
        return None
    target = Path(configured).expanduser().resolve()
    if target.drive.upper() != 'G:':
        raise ValueError('安装确认截图只允许保存到 G 盘。')
    result = subprocess.run([str(ADB), '-s', DEVICE, 'exec-out', 'screencap', '-p'],
                            capture_output=True, timeout=20, creationflags=NO_WINDOW)
    if result.returncode or not result.stdout.startswith(b'\x89PNG\r\n\x1a\n'):
        raise RuntimeError('无法在自动确认前保存有效的安装提示截图。')
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(result.stdout)
    return str(target)


def _auto_confirm_usb_install(package_name, application_label):
    """CPU-OCR confirms only the OS USB-install prompt naming this exact APK label."""
    snap = android_coordinates.snapshot(_adb, _screenshot, _require_device)
    state = android_coordinates._load(snap['snapshot_id'])
    ocr_result = android_coordinates.ocr(snap['snapshot_id'], '', 'contains', .35, 120)
    rows = ocr_result.get('matches', [])
    visible_text = [str(row.get('text') or '').strip() for row in rows]
    prompt_markers = ('USB安装提示', '通过USB安装', 'USB install', 'Install via USB')
    is_prompt = any(marker.casefold() in value.casefold() for marker in prompt_markers for value in visible_text)
    if not is_prompt:
        return {'detected': False, 'confirmed': False, 'reason': '未出现 USB 安装确认。'}
    expected_labels = ([application_label] if isinstance(application_label, str) else list(application_label or []))
    expected_labels = [str(value).strip() for value in expected_labels if str(value).strip()]
    matched_labels = [label for label in expected_labels if sum(value == label for value in visible_text) == 1]
    if len(matched_labels) != 1:
        raise RuntimeError(f'检测到 USB 安装确认，但界面未显示待安装 APK 清单中的精确应用名称（{expected_labels or [package_name]}）；已停止，不会点确认。')
    matched_label = matched_labels[0]
    confirm_labels = ('继续安装', '继续', 'Continue install', 'Install anyway')
    confirm_rows = [row for row in rows if str(row.get('text') or '').strip() in confirm_labels
                    and row.get('bbox') and len(row['bbox']) == 4]
    if len(confirm_rows) != 1:
        raise RuntimeError('USB 安装确认与 APK 名称匹配，但 CPU OCR 未找到唯一的“继续安装”文字框；已停止，不会盲点屏幕。')
    left, top, right, bottom = map(int, confirm_rows[0]['bbox'])
    mapped = android_coordinates.map_point(state['snapshot_id'], (left + right) / 2,
        (top + bottom) / 2, state['width'], state['height'])
    x, y = mapped['device_point']
    prompt_screenshot = _capture_install_prompt_screenshot() or state['screenshot_path']
    confirmation_method = 'adb-shell'
    try:
        tap_result = android_coordinates.click(_adb, _screenshot, _require_device,
            state['snapshot_id'], device_point=[x, y])
    except RuntimeError as error:
        if 'INJECT_EVENTS' not in str(error):
            raise
        # This exact APK label and button were OCR-matched; retry the guarded click
        # through the already-authorized root input path only after shell denial.
        tap_result = android_coordinates.click(_adb, _screenshot, _require_device,
            state['snapshot_id'], device_point=[x, y], use_root=True)
        confirmation_method = 'root-su'
    for _ in range(12):
        after_snapshot = tap_result['after']
        after_result = android_coordinates.ocr(after_snapshot['snapshot_id'], '', 'contains', .35, 120)
        after_text = [str(row.get('text') or '').strip() for row in after_result.get('matches', [])]
        if not (any(marker.casefold() in value.casefold() for marker in prompt_markers for value in after_text)
                and matched_label in after_text):
            break
        time.sleep(0.4)
        tap_result = {'after': android_coordinates.snapshot(_adb, _screenshot, _require_device)}
    else:
        raise RuntimeError('已点按“继续安装”，但手机仍显示同一 APK 的 USB 安装确认；安装未继续。')
    return {'detected': True, 'confirmed': True, 'application_label': matched_label,
            'matched_manifest_label': matched_label,
            'manifest_labels': expected_labels,
            'confirmation_text': '继续安装', 'screen_coordinate': [x, y],
            'confirmation_method': confirmation_method, 'prompt_screenshot': prompt_screenshot}


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
    info = _device_info()['properties']
    device_api = int(info['ro.build.version.sdk'])
    _, abi_text = _adb('shell', 'getprop', 'ro.product.cpu.abilist')
    device_abis = set(abi_text.strip().split(',')) or {info['ro.product.cpu.abi']}
    for item in paths:
        resolved=Path(item).expanduser().resolve(strict=True)
        if resolved.drive.upper()!='G:':
            raise ValueError('APK 自动安装只接受 G 盘中的 APK 文件。')
        meta = _apk_metadata(resolved)
        if not meta['package_name']:
            raise ValueError('无法验证 APK 包名；未执行安装。请安装 SDK apkanalyzer 或配置 aapt2。')
        if meta['package_name'] != package_name:
            raise ValueError(f"APK 包名不符：{meta['path']} 包含 {meta['package_name']}，预期 {package_name}。")
        if meta.get('min_sdk') is None or meta.get('version_code') is None:
            raise ValueError('无法验证 APK minSDK/版本；未执行安装。')
        if meta['min_sdk'] > device_api:
            raise ValueError(f"APK 需要 API {meta['min_sdk']}，设备只有 API {device_api}。")
        if meta.get('native_abis') and not device_abis.intersection(meta['native_abis']):
            raise ValueError('APK 原生 ABI 与指定设备不匹配；未执行安装。')
        if meta['certificate_sha256'] != expected:
            raise ValueError(f"APK 签名证书不符：{meta['path']} SHA256={meta['certificate_sha256']}，预期={expected}。")
        verified.append(meta)
    if len({meta['version_code'] for meta in verified}) != 1:
        raise ValueError('split APK 的版本不一致；未执行安装。')
    args = ['install', '-r'] if len(verified) == 1 else ['install-multiple', '-r']
    if replace:
        args.append('-d')
    args.extend(item['path'] for item in verified)
    code, output = _adb(*args, timeout=300)
    if code or 'Success' not in output:
        raise RuntimeError(f'ADB 安装失败 ({code})：{output}')
    confirmation = _auto_confirm_usb_install(
        package_name, verified[0].get('application_labels') or verified[0].get('application_label'))
    check_code, package_path = _adb('shell', 'pm', 'path', package_name, timeout=20)
    if check_code or 'package:' not in package_path:
        raise RuntimeError('ADB 回报安装成功，但设备包管理器查不到目标包：' + package_path)
    return {'serial': DEVICE, 'package_name': package_name, 'installed': True, 'adb_result': output,
            'package_path': package_path, 'apk_signatures_checked': verified,
            'usb_install_confirmation': confirmation, 'launched': False}


def _push_apk(apk_path, destination_name=''):
    """Verify a local APK and copy it to the selected phone without installing it."""
    _require_device()
    path=Path(apk_path).expanduser().resolve(strict=True)
    if path.suffix.lower()!='.apk' or path.drive.upper()!='G:':
        raise ValueError('APK 推送只接受 G 盘中的 .apk 文件。')
    meta=_apk_metadata(path)
    name=str(destination_name or path.name)
    if (len(name)>160 or not re.fullmatch(r'(?i)[a-z0-9][a-z0-9._-]*\.apk',name)
            or '..' in name or '/' in name or '\\' in name):
        raise ValueError('目标文件名只能包含字母、数字、点、下划线和连字符，并以 .apk 结尾。')
    remote='/sdcard/Download/'+name
    code,output=_adb('shell','mkdir','-p','/sdcard/Download',timeout=20)
    if code:
        raise RuntimeError(f'准备手机 Download 目录失败 ({code})：{output}')
    code,output=_adb('push',str(path),remote,timeout=300)
    if code or 'pushed' not in output.lower():
        raise RuntimeError(f'APK 复制失败 ({code})：{output}')
    local_sha=hashlib.sha256(path.read_bytes()).hexdigest()
    code,remote_result=_adb('shell','sha256sum',remote,timeout=40)
    if code:
        raise RuntimeError(f'已复制 APK，但无法读取手机端 SHA-256 ({code})：{remote_result}')
    remote_sha=remote_result.split()[0].lower() if remote_result.split() else ''
    if remote_sha!=local_sha:
        raise RuntimeError('已复制 APK，但手机端与 G 盘源文件 SHA-256 不一致。')
    props=_device_info()['properties']
    return {'serial':DEVICE,'device_model':props.get('ro.product.model'),'destination':remote,
            'package_name':meta.get('package_name'),'version_code':meta.get('version_code'),
            'certificate_sha256':meta.get('certificate_sha256'),'size_bytes':path.stat().st_size,
            'sha256':local_sha,'remote_sha256_matches':True,'pushed':True,'installed':False,'launched':False}


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
    target = Path(destination).expanduser() if destination else Path(r'G:\LocalCodex\logs\android') / f'screen-{int(time.time())}.png'
    target.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run([str(ADB), '-s', DEVICE, 'exec-out', 'screencap', '-p'], capture_output=True,
                            timeout=30, creationflags=NO_WINDOW)
    if result.returncode or not result.stdout.startswith(b'\x89PNG\r\n\x1a\n'):
        raise RuntimeError(f'设备截图不是有效 PNG (exit={result.returncode})：{result.stderr.decode("utf-8",errors="replace")[:500]}')
    target.write_bytes(result.stdout)
    return {'serial': DEVICE, 'path': str(target.resolve()), 'bytes': len(result.stdout), 'png_valid': True}


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
                from process_identity import process_identity
                expected = (owned.get(key) or {}).get('identity')
                alive = bool(expected and process_identity(pid) == expected)
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
    # Scope software display settings to the design process, never the LLM.
    env.update({str(k): str(v) for k, v in app.get('environment', {}).items()
                if k in ('QT_OPENGL', 'QT_QUICK_BACKEND')})
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
    from process_identity import process_identity
    identity = process_identity(managed_pid)
    owned[name] = {'pid': managed_pid, 'launcher_pid': process.pid, 'started_at': time.time(),
                   'identity': identity,
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
    from process_identity import terminate_verified
    pid = item['pid']
    stopped = terminate_verified(item.get('identity'))
    if stopped:
        owned.pop(name, None)
        _write_design_processes(owned)
    return {'app': name, 'pid': pid, 'stopped': stopped,
            'reason': '已核对进程句柄、程序路径和创建时间。' if stopped else '记录缺少身份或已过期；没有终止进程。'}


def _schemas():
    from tool_directory import SCHEMA as DIRECTORY_SCHEMA
    return {
        'tool-directory':[DIRECTORY_SCHEMA],
        'android-coordinates': android_coordinates.schemas(),
        'model-manager': [
            ('model_list', '列出内置和本地注册的 GGUF 模型。', {'type':'object','properties':{}}),
            ('model_search', '搜索真实公开发布的 Hugging Face 文本生成模型。', {'type':'object','properties':{'query':{'type':'string'},'limit':{'type':'integer','default':20}},'required':['query']}),
            ('model_inspect', '读取模型卡、提交 SHA、可用 GGUF 文件与可信哈希。', {'type':'object','properties':{'repo_id':{'type':'string'},'revision':{'type':'string'}},'required':['repo_id']}),
            ('model_download', '按不可变提交与 Hub SHA256 断点续传下载单个 GGUF；不会自动切换。', {'type':'object','properties':{'repo_id':{'type':'string'},'revision':{'type':'string'},'filename':{'type':'string'}},'required':['repo_id','revision','filename']}),
            ('model_download_status', '查询下载进度。', {'type':'object','properties':{'job_id':{'type':'string'}},'required':['job_id']}),
            ('model_download_cancel', '请求取消下载并保留 partial 供断点续传。', {'type':'object','properties':{'job_id':{'type':'string'}},'required':['job_id']}),
            ('model_register', '将本地 GGUF 的已读元数据加入共享模型注册表；不代表运行通过。', {'type':'object','properties':{'path':{'type':'string'},'display_name':{'type':'string'},'projector_path':{'type':'string'}},'required':['path']}),
            ('model_validate', '后台旁路加载验证模型：中文、原生工具、需要的视觉；不切换当前模型。', {'type':'object','properties':{'model_id':{'type':'string'},'hash_file':{'type':'boolean','default':False}},'required':['model_id']}),
            ('model_validation_status', '查询旁路模型验证状态和真实输出证据。', {'type':'object','properties':{'job_id':{'type':'string'}},'required':['job_id']}),
            ('model_validation_cancel', '取消旁路验证，只结束该验证拥有的进程。', {'type':'object','properties':{'job_id':{'type':'string'}},'required':['job_id']}),
            ('model_activate', '将已通过运行时验证的模型排入安全切换队列。', {'type':'object','properties':{'model_id':{'type':'string'}},'required':['model_id']}),
            ('model_rollback', '排入切回上一成功模型的请求。', {'type':'object','properties':{}}),
        ],
        'android': [
            ('android_devices', '列出 ADB 设备；任何操作只允许指定序列号。', {'type':'object','properties':{}}),
            ('android_device_info', '读取指定设备的 ROM、Android、API、ABI 和 Google 组件状态。', {'type':'object','properties':{}}),
            ('android_packages', '列出设备上已安装的第三方包，可按前缀过滤。', {'type':'object','properties':{'prefix':{'type':'string','default':''}}}),
            ('android_apk_inspect', '读取 APK 包名并用 apksigner 验证签名。', {'type':'object','properties':{'apk_path':{'type':'string'}},'required':['apk_path']}),
            ('android_push_apk', '验证 G 盘 APK 签名后，只复制到已连接手机的 Download 文件夹；不会安装或启动。', {'type':'object','properties':{'apk_path':{'type':'string'},'destination_name':{'type':'string','maxLength':160}},'required':['apk_path']}),
            ('android_install_apks', '自动安装 G 盘 APK；必须先核对包名和签名 SHA256，再提供精确包名、可信证书 SHA256；同时检查最低 Android 版本、ABI 和 split 版本；只操作已固定的设备，不启动应用。', {'type':'object','properties':{'apk_paths':{'type':'array','items':{'type':'string'}},'package_name':{'type':'string'},'expected_certificate_sha256':{'type':'string'},'allow_downgrade':{'type':'boolean','default':False}},'required':['apk_paths','package_name','expected_certificate_sha256']}),
            ('android_launch', '启动已安装应用；登录/授权停留在用户操作界面。', {'type':'object','properties':{'package_name':{'type':'string'}},'required':['package_name']}),
            ('android_screenshot', '保存并验证真实二进制 PNG 设备截图；可见文字应在同一帧运行 CPU OCR，不查询无障碍树。', {'type':'object','properties':{'destination':{'type':'string','default':''}}}),
            ('android_logcat', '读取最近设备日志；给出包名时按进程 PID 定向。', {'type':'object','properties':{'package_name':{'type':'string','default':''},'lines':{'type':'integer','default':300}}}),
        ] + android_coordinates.schemas(),
        'design-control': [
            ('design_status', '查询 Blender/FreeCAD 受管进程、RPC 端口和任务目录。', {'type':'object','properties':{}}),
            ('blender_start', '按需启动受管 Blender 图形界面并等待 MCP 插件连接。', {'type':'object','properties':{'job_dir':{'type':'string','default':''}}}),
            ('blender_stop', '仅关闭本工作台自己启动并记录 PID 的 Blender 进程树。', {'type':'object','properties':{}}),
            ('freecad_start', '按需启动受管 FreeCAD 图形界面及 MCP 插件。', {'type':'object','properties':{'job_dir':{'type':'string','default':''}}}),
            ('freecad_stop', '仅关闭本工作台自己启动并记录 PID 的 FreeCAD 进程树。', {'type':'object','properties':{}}),
        ],
        'scopeweaver-source': [
            ('scopeweaver_source_info', '读取 ScopeWeaver 源码镜像、提交历史和许可证声明；只查本地文件，不连接或启动服务。', {'type':'object','properties':{}}),
            ('scopeweaver_search_source', '只在本地 ScopeWeaver 源码中搜索文本；不会运行代码、安装程序、联网或发起扫描。', {'type':'object','properties':{'query':{'type':'string','minLength':2,'maxLength':200},'limit':{'type':'integer','minimum':1,'maximum':20}} ,'required':['query']}),
            ('scopeweaver_read_source', '读取本地 ScopeWeaver 仓库中的小型文本源文件；拒绝越界路径、密钥文件和大文件。', {'type':'object','properties':{'relative_path':{'type':'string','maxLength':300},'max_chars':{'type':'integer','minimum':1,'maximum':12000}},'required':['relative_path']}),
        ],
        'vmware': [
            ('vmware_status', '只读检查本机 VMware Workstation 与 vmrun 程序文件是否存在；不会启动 VMware 主程序。', {'type':'object','properties':{}}),
            ('vmware_list_running_vms', '只读列出当前运行中的本机 VMware 虚拟机；不更改虚拟机状态。', {'type':'object','properties':{}}),
        ],
    }


def _dispatch(service, name, args):
    if service=='tool-directory' and name=='tool_catalog_search':
        from tool_directory import search
        return search(**args)
    if service in ('android','android-coordinates') and name in ('screen_prepare_vision','screen_map_prepared_point'):
        from vision_crop import prepare,map_view
        return (prepare if name=='screen_prepare_vision' else map_view)(**args)
    if service in ('android','android-coordinates') and name=='screen_map_point':
        from screen_coordinates import map_point
        return map_point(**args)
    if service in ('android','android-coordinates') and name=='screen_ocr':
        from screen_coordinates import ocr_image
        return ocr_image(**args)
    if service in ('android','android-coordinates') and name=='screen_find_symbol':
        from screen_coordinates import find_symbol_image
        return find_symbol_image(**args)
    if service == 'voice':
        from creative_tools import dispatch
        return dispatch(ROOT, service, name, args)
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
        if name in ('model_validation_status', 'model_validation_cancel'):
            from model_validation import validation_status, cancel_validation
            return (validation_status if name.endswith('_status') else cancel_validation)(ROOT, args['job_id'])
        if name == 'model_activate': return _model_activate(args['model_id'])
        if name == 'model_rollback':
            history = ROOT / 'model-activation-history.json'
            rows = json.loads(history.read_text(encoding='utf-8')) if history.exists() else []
            if len(rows) < 2: raise ValueError('还没有足够的成功切换记录用于回退。')
            return _model_activate(rows[-2]['model_id'])
    if service in ('android','android-coordinates') and name.startswith('android_ui_'):
        return android_coordinates.dispatch(name,args,_adb,_screenshot,_require_device)
    if service == 'android':
        if name == 'android_devices': return _device_list()
        if name == 'android_device_info': return _device_info()
        if name == 'android_packages': return _packages_list(args.get('prefix',''))
        if name == 'android_apk_inspect': return _apk_metadata(args['apk_path'])
        if name == 'android_push_apk': return _push_apk(args['apk_path'], args.get('destination_name',''))
        if name == 'android_install_apks': return _install_apks(args['apk_paths'], args['package_name'], args['expected_certificate_sha256'], bool(args.get('allow_downgrade',False)))
        if name == 'android_launch': return _launch_package(args['package_name'])
        if name == 'android_screenshot':
            try:
                result=android_coordinates.snapshot(_adb,_screenshot,_require_device)
            except (OSError,RuntimeError,ValueError) as error:
                result=_screenshot(args.get('destination',''))
                return result | {'screenshot_only':True,'ocr_required_for_text':True,'note':'Run CPU OCR on this screenshot for text targets; use CPU symbol/template matching for glyphs. Do not query an accessibility tree or guess taps.','capture_error':str(error)[:300]}
            destination=args.get('destination','')
            if destination:
                target=Path(destination).expanduser();target.parent.mkdir(parents=True,exist_ok=True)
                target.write_bytes(Path(result['screenshot_path']).read_bytes())
                from ui_image_gate import register_snapshot
                register_snapshot(target,android_coordinates._load(result['snapshot_id']))
                result['path']=str(target.resolve())
            else:result['path']=result['screenshot_path']
            return result | {'screenshot_only':True,'ocr_required_for_text':True,'note':'This snapshot contains an original-size screenshot only. For text call android_ui_ocr on this snapshot; for glyphs use CPU symbol/template matching. General vision is only a last fallback.'}
        if name == 'android_logcat': return _logcat(args.get('package_name',''), args.get('lines',300))
    if service == 'design-control':
        if name == 'design_status': return _design_status()
        if name == 'blender_start': return _start_design_app('blender', args.get('job_dir',''))
        if name == 'blender_stop': return _stop_design_app('blender')
        if name == 'freecad_start': return _start_design_app('freecad', args.get('job_dir',''))
        if name == 'freecad_stop': return _stop_design_app('freecad')
    if service == 'scopeweaver-source':
        if name == 'scopeweaver_source_info': return _scopeweaver_source_info()
        if name == 'scopeweaver_search_source': return _scopeweaver_search_source(args['query'], args.get('limit',10))
        if name == 'scopeweaver_read_source': return _scopeweaver_read_source(args['relative_path'], args.get('max_chars',6000))
    if service == 'vmware':
        if name == 'vmware_status': return _vmware_status()
        if name == 'vmware_list_running_vms': return _vmware_list_running_vms()
    raise ValueError('未实现或不支持的工具：' + name)


SCOPEWEAVER_SOURCE_ROOT = Path(r'G:\LocalCodex-work\scopeweaver-review-20261009')
SCOPEWEAVER_UPSTREAM_BASE = '160fe13'
SCOPEWEAVER_ALLOWED_SUFFIXES = {'.go','.md','.txt','.ts','.tsx','.js','.jsx','.json','.yaml','.yml','.toml','.sql','.sh','.bat','.py','.html','.css'}
SCOPEWEAVER_IGNORED_PARTS = {'.git','node_modules','dist','build','data','logs','vendor','coverage'}
SCOPEWEAVER_MAX_FILE_BYTES = 256_000


def _scopeweaver_root():
    root = Path(os.environ.get('LOCAL_CODEX_SCOPEWEAVER_SOURCE_ROOT', str(SCOPEWEAVER_SOURCE_ROOT))).resolve()
    if not root.is_dir() or not (root / 'README.md').is_file() or not (root / 'LICENSE').is_file():
        raise FileNotFoundError('ScopeWeaver 本地源码副本不存在或缺少 README/LICENSE；请先检查 G 盘源码目录。')
    return root


def _scopeweaver_safe_file(relative_path):
    if not isinstance(relative_path, str) or not relative_path or len(relative_path) > 300:
        raise ValueError('请提供仓库内的相对文件路径。')
    candidate = Path(relative_path)
    if candidate.is_absolute() or candidate.drive or any(part in ('..', '') for part in candidate.parts):
        raise ValueError('只允许读取 ScopeWeaver 仓库内的相对路径。')
    if any(part.casefold() in SCOPEWEAVER_IGNORED_PARTS for part in candidate.parts):
        raise ValueError('此目录不在源码审查范围内。')
    if candidate.suffix.casefold() not in SCOPEWEAVER_ALLOWED_SUFFIXES or candidate.name.casefold().startswith('.env') or candidate.name.casefold() in {'config.json','secrets.json'}:
        raise ValueError('此文件类型不在安全的文本源码白名单内。')
    root = _scopeweaver_root()
    target = (root / candidate).resolve()
    if not target.is_relative_to(root):
        raise ValueError('拒绝读取仓库边界外的链接或路径。')
    if not target.is_file():
        raise FileNotFoundError('仓库中没有该普通文件。')
    if target.stat().st_size > SCOPEWEAVER_MAX_FILE_BYTES:
        raise ValueError('文件超过 256 KB 上限；请改用源码搜索。')
    return target


def _scopeweaver_source_info():
    root = _scopeweaver_root()
    commit = first_commit = commit_count = None
    try:
        result = subprocess.run(['git','rev-parse','HEAD'], cwd=str(root), capture_output=True,
                                text=True, timeout=3, check=True, creationflags=NO_WINDOW)
        commit = result.stdout.strip()[:40]
        first = subprocess.run(['git','log','--all','--reverse','--format=%H','-1'], cwd=str(root),
                               capture_output=True,text=True,timeout=5,check=True,creationflags=NO_WINDOW)
        first_commit=first.stdout.strip()[:40]
        count=subprocess.run(['git','rev-list','--count','HEAD'],cwd=str(root),capture_output=True,
                             text=True,timeout=5,check=True,creationflags=NO_WINDOW)
        commit_count=int(count.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        pass
    readme = (root / 'README.md').read_text(encoding='utf-8', errors='replace')[:1800]
    return {'repository':'cskwork/scopeweaver','derived_from':'Autumn-27/ARTEX',
            'upstream_base_commit':SCOPEWEAVER_UPSTREAM_BASE,'commit':commit,'first_commit':first_commit,
            'commit_count':commit_count,'history_preserved':bool(first_commit and commit_count and commit_count>1),
            'license':'AGPL-3.0','local_path':str(root),'runtime_installed':False,
            'scope':'仅源码阅读、学习与代码审查；本 MCP 不安装或启动 ScopeWeaver，不连接其服务，不创建/恢复任务，也不扫描、探测或利用任何目标。',
            'author_notice':'仓库声明仅供源码研究和隔离环境技术验证，并禁止对网站、在线服务或联网系统开展实际扫描、探测、利用或真实渗透测试。',
            'readme_excerpt':readme[:500]}


def _scopeweaver_source_files(root):
    found = []
    for current, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = sorted(name for name in dirs if name.casefold() not in SCOPEWEAVER_IGNORED_PARTS)
        for name in files:
            path = Path(current) / name
            rel = path.relative_to(root)
            if path.suffix.casefold() not in SCOPEWEAVER_ALLOWED_SUFFIXES or name.casefold().startswith('.env') or name.casefold() in {'config.json','secrets.json'}:
                continue
            try:
                if path.is_symlink() or not path.resolve().is_relative_to(root) or path.stat().st_size > SCOPEWEAVER_MAX_FILE_BYTES:
                    continue
            except OSError:
                continue
            found.append((rel.as_posix(),path))
            if len(found) >= 2500:
                return found
    return found


def _scopeweaver_search_source(query, limit=10):
    if not isinstance(query,str) or not 2 <= len(query.strip()) <= 200:
        raise ValueError('搜索词长度应为 2 至 200 个字符。')
    limit = int(limit)
    if not 1 <= limit <= 20:
        raise ValueError('limit 必须在 1 至 20 之间。')
    root = _scopeweaver_root()
    needle = query.strip().casefold()
    hits = []
    for rel,path in _scopeweaver_source_files(root):
        try:
            lines = path.read_text(encoding='utf-8-sig').splitlines()
        except (OSError, UnicodeError):
            continue
        for index,line in enumerate(lines,1):
            if needle in line.casefold():
                hits.append({'path':rel,'line':index,'excerpt':line.strip()[:500]})
                if len(hits) >= limit:
                    return {'query':query,'hits':hits,'truncated':True,'source_only':True}
    return {'query':query,'hits':hits,'truncated':False,'source_only':True}


def _scopeweaver_read_source(relative_path, max_chars=6000):
    max_chars = int(max_chars)
    if not 1 <= max_chars <= 12000:
        raise ValueError('max_chars 必须在 1 至 12,000 之间。')
    path = _scopeweaver_safe_file(relative_path)
    text = path.read_text(encoding='utf-8-sig')
    return {'path':path.relative_to(_scopeweaver_root()).as_posix(),'text':text[:max_chars],
            'total_chars':len(text),'truncated':len(text)>max_chars,'source_only':True}


VMWARE_EXE = Path(r'G:\VMware\vmware.exe')
VMRUN_EXE = Path(r'G:\VMware\vmrun.exe')


def _vmware_status():
    if not VMWARE_EXE.is_file() or not VMRUN_EXE.is_file():
        return {'installed':False,'vmware_exe':str(VMWARE_EXE),'vmrun_exe':str(VMRUN_EXE)}
    return {'installed':True,'vmware_exe':str(VMWARE_EXE),'vmrun_exe':str(VMRUN_EXE),
            'vmware_size_bytes':VMWARE_EXE.stat().st_size,'vmrun_size_bytes':VMRUN_EXE.stat().st_size,
            'scope':'只读文件状态和运行列表；不启动 VMware GUI，不控制 VM 电源或快照。'}


def _vmware_list_running_vms():
    if not VMRUN_EXE.is_file():
        raise FileNotFoundError('G:\\VMware\\vmrun.exe 不存在，无法读取运行列表。')
    try:
        result=subprocess.run([str(VMRUN_EXE),'-T','ws','list'],capture_output=True,text=True,timeout=10,
                              check=False,creationflags=NO_WINDOW)
    except (OSError,subprocess.SubprocessError) as error:
        raise RuntimeError(f'读取 VMware 运行列表失败：{type(error).__name__}: {error}') from error
    output=(result.stdout or result.stderr).replace('\r','')
    lines=[line.strip() for line in output.splitlines() if line.strip()]
    vms=[]
    if lines:
        for line in lines[1:]:
            if line.lower().endswith('.vmx'):
                vms.append(line)
    return {'exit_code':result.returncode,'count':len(vms),'vms':vms,'raw_summary':lines[0] if lines else '',
            'read_only':True}


def serve(service):
    schemas = _schemas().get(service)
    if schemas is None:
        from creative_tools import schemas as creative_schemas
        schemas = creative_schemas(service)
    if not schemas:
        raise ValueError('MCP service name is not recognized.')
    read_only = service in ('scopeweaver-source','vmware')
    tools = [{'name': name, 'description': description, 'inputSchema': schema,
              'annotations':{'readOnlyHint':read_only,'destructiveHint':False,'openWorldHint':False}}
             for name, description, schema in schemas]
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
                    'capabilities':{'tools':{'listChanged':False}},'serverInfo':{'name':'mycodex-'+service,'version':'63.0'}})
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
        raise SystemExit('usage: local_mcp_servers.py model-manager|android|design-control|scopeweaver-source')
    serve(sys.argv[1])
