"""Read-only local-workbench backup; preserve live SQLite with its online backup API."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import time

ROOT = Path(r'D:\LocalCodex')
PROJECTS = Path(r'C:\my_projects')
SOURCE = Path(r'C:\Users\18213\Desktop\codexx')
CLI = Path(r'C:\Users\18213\Desktop\codex-jack-cli')
SKIP_DIRS = {'__pycache__', 'build', 'dist', 'node_modules', '.pytest_cache',
             '.tmp', 'tmp', 'thread-writer-locks'}
SKIP_NAMES = {'model.lock', 'model.pid', 'adapter.pid', 'gateway.pid'}


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        while chunk := stream.read(4 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def is_reparse(path: Path) -> bool:
    return bool(getattr(path.lstat(), 'st_file_attributes', 0) & 0x400)


def inventory(source: Path, destination: Path, excluded: list[dict]) -> list[tuple[Path, Path]]:
    files = []
    for folder, dirs, names in os.walk(source, followlinks=False):
        parent = Path(folder)
        keep = []
        for name in dirs:
            path = parent / name
            if name in SKIP_DIRS or is_reparse(path):
                excluded.append({'path': str(path), 'reason': 'cache, temporary directory or reparse point'})
            else:
                keep.append(name)
        dirs[:] = keep
        for name in names:
            path = parent / name
            if name in SKIP_NAMES or name.endswith(('.pid', '.lock')) or is_reparse(path):
                excluded.append({'path': str(path), 'reason': 'process state or reparse point'})
            elif any(name.endswith(suffix) and path.with_name(name[:-len(suffix)]).exists()
                     for suffix in ('-wal', '-shm', '-journal')):
                excluded.append({'path': str(path), 'reason': 'SQLite sidecar included through online database backup'})
            else:
                files.append((path, destination / path.relative_to(source)))
    return files


def copy_snapshot(source: Path, destination: Path) -> dict:
    destination.parent.mkdir(parents=True, exist_ok=True)
    before = source.stat()
    with source.open('rb') as stream:
        sqlite = stream.read(16) == b'SQLite format 3\0'
    if sqlite:
        deadline = time.monotonic() + 60
        def progress(*_):
            if time.monotonic() > deadline:
                raise TimeoutError(f'SQLite snapshot timed out: {source}')
        origin = sqlite3.connect(source.resolve().as_uri() + '?mode=ro', uri=True, timeout=10)
        target = sqlite3.connect(destination)
        try:
            origin.backup(target, pages=512, progress=progress, sleep=.05)
            check = [row[0] for row in target.execute('PRAGMA quick_check')]
            if check != ['ok']:
                raise RuntimeError(f'Database integrity failed: {source}: {check}')
        finally:
            target.close()
            origin.close()
        digest = sha(destination)
        kind = 'sqlite_online_backup'
    else:
        # Copy exactly the byte range present at snapshot start, even if a log is appended later.
        last_error = None
        for attempt in range(3):
            before = source.stat()
            expected = before.st_size
            copied = 0
            digestor = hashlib.sha256()
            try:
                with source.open('rb') as origin, destination.open('wb') as target:
                    while copied < expected:
                        chunk = origin.read(min(4 * 1024 * 1024, expected - copied))
                        if not chunk:
                            raise OSError(f'Source changed while being copied: {source}')
                        target.write(chunk)
                        digestor.update(chunk)
                        copied += len(chunk)
                after = source.stat()
                if (after.st_mtime_ns != before.st_mtime_ns or after.st_size != expected) and source.suffix not in ('.log', '.jsonl'):
                    raise OSError(f'Source changed while being copied: {source}')
                digest = digestor.hexdigest()
                last_error = None
                break
            except OSError as error:
                last_error = error
                time.sleep(.1)
        if last_error:
            raise last_error
        kind = 'byte_snapshot'
    after = source.stat()
    return {'source': str(source), 'path': str(destination), 'bytes': destination.stat().st_size,
            'sha256': digest, 'kind': kind, 'source_mtime_ns': before.st_mtime_ns,
            'source_changed_during_copy': after.st_mtime_ns != before.st_mtime_ns or after.st_size != before.st_size}


def main():
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    stamp = datetime.now(timezone(timedelta(hours=8))).strftime('%Y%m%d-%H%M%S')
    destination = PROJECTS / f'MyCodex-v24-backup-{stamp}'
    parent = PROJECTS.resolve(strict=True)
    if destination.resolve().parent != parent:
        raise RuntimeError('Backup must be an immediate child of the requested project directory.')
    if destination.exists():
        raise FileExistsError(destination)
    deployment = json.loads((ROOT / 'deployment-steering24.json').read_text(encoding='utf-8-sig'))
    executable = Path(deployment['executable']).resolve(strict=True)
    if executable.parent.parent != (ROOT / 'app').resolve():
        raise RuntimeError('Unexpected current application directory.')
    excluded = []
    groups = [('source-workbench', SOURCE, destination / 'source-workbench'),
              ('source-cli', CLI, destination / 'source-cli'),
              ('current-app', executable.parent, destination / 'deployment/app' / executable.parent.name)]
    for name in ('engine', 'runtime', 'runtime-hip', 'codex-home', 'conversations',
                 'history', 'logs', 'tasks', 'verification-project', 'licenses', 'diagnostics'):
        groups.append((name, ROOT / name, destination / 'deployment' / name))
    jobs = []
    for label, source, target in groups:
        if source.exists():
            batch = inventory(source, target, excluded)
            jobs.extend((label, source, target) for source, target in batch)
    for path in ROOT.iterdir():
        if path.is_file() and path.name not in SKIP_NAMES and not is_reparse(path):
            jobs.append(('deployment-config-reports', path, destination / 'deployment' / path.name))
    for name in ('jack-local.config.toml', 'huihui-local.config.toml'):
        path = Path.home() / '.codex' / name
        if path.exists():
            jobs.append(('launcher-profiles', path, destination / 'launcher-profiles' / name))
    for name in ('我的Codex.cmd', '启动Jack-Codex.cmd'):
        path = Path.home() / 'Desktop' / name
        if path.exists():
            jobs.append(('desktop-shortcuts', path, destination / 'desktop-shortcuts' / name))
    migration_prompt = PROJECTS / '模型迁移提示词-v24.txt'
    if migration_prompt.exists():
        jobs.append(('migration-prompt', migration_prompt, destination / migration_prompt.name))
    total = sum(source.stat().st_size for _, source, _ in jobs)
    if shutil.disk_usage(PROJECTS).free < total + 2 * 1024 ** 3:
        raise RuntimeError('Not enough free space for the backup and 2 GiB of headroom.')
    destination.mkdir()
    report = {'phase': 'copying', 'path': str(destination), 'created_at': datetime.now(timezone(timedelta(hours=8))).isoformat(),
              'version': deployment['adapter_version'], 'files': [], 'excluded': excluded,
              'models_copied': False, 'processes_interrupted': False,
              'source_app': str(executable), 'errors': []}
    report_path = destination / 'backup-manifest.json'
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'phase': 'copying', 'path': str(destination), 'file_count': len(jobs), 'estimated_bytes': total}), flush=True)
    current_label = None
    try:
        for label, source, target in jobs:
            if current_label != label:
                current_label = label
                print(json.dumps({'group': label}), flush=True)
            record = copy_snapshot(source, target)
            record['path'] = str(target.relative_to(destination))
            report['files'].append(record)
        models = []
        settings = json.loads((destination / 'deployment/settings.json').read_text(encoding='utf-8-sig'))
        model_directory = Path(settings.get('model_directory', str(ROOT / 'models')))
        for path in sorted(model_directory.glob('*.gguf')):
            st = path.stat()
            with path.open('rb') as stream:
                head_hash = hashlib.sha256(stream.read(1024 * 1024)).hexdigest()
            models.append({'path': str(path.resolve()), 'bytes': st.st_size, 'mtime_ns': st.st_mtime_ns,
                           'first_1MiB_sha256': head_hash, 'copied': False})
        model_report = destination / 'models-reference.json'
        model_report.write_text(json.dumps({'models': models}, ensure_ascii=False, indent=2), encoding='utf-8')
        report['phase'] = 'verifying'
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({'phase': 'verifying', 'file_count': len(report['files'])}), flush=True)
        for record in report['files']:
            path = destination / record['path']
            if path.stat().st_size != record['bytes'] or sha(path) != record['sha256']:
                raise RuntimeError(f'Backup checksum mismatch: {path}')
        notes = destination / '备份说明.txt'
        notes.write_text(
            'MyCodex v24 备份\n\n'
            f'时间（北京时间）：{report["created_at"]}\n'
            f'原程序：{executable}\n\n'
            'deployment：当前程序、Codex 引擎、Vulkan/HIP 运行时、设置、原生会话、对话索引、历史、日志、草稿和测试作品。\n'
            'source-workbench：桌面工作台源码、验证、打包和部署资料。\n'
            'source-cli：独立 CLI 项目和经验，含其配置及会话。\n'
            'launcher-profiles、desktop-shortcuts：原有入口配置。\n\n'
            '大模型没有复制：原权重仍在 G:\\LocalCodex\\models，路径和大小见 models-reference.json。\n'
            '缓存、构建临时目录、进程锁/PID、旧版本安装和旧备份没有重复复制。SQLite 使用在线一致性备份，WAL 内容已包含在数据库中。\n'
            '对话和日志保存的是备份时已经写入的内容，不自动同步后续对话。\n'
            '当前工作台和模型未被关闭或修改。这是快照目录，不要直接运行里面的部署脚本覆盖现有程序。\n'
            '恢复时先确认无活动回答，再将需要的源码或 deployment 中对应内容恢复到原路径；不要恢复旧进程编号。\n'
            '原路径包括 D:\\LocalCodex、C:\\Users\\18213\\Desktop\\codexx 和 C:\\Users\\18213\\Desktop\\codex-jack-cli。\n'
            '完整文件清单、大小和 SHA-256 在 backup-manifest.json。\n', encoding='utf-8')
        report['auxiliary_files'] = [{'path': path.name, 'bytes': path.stat().st_size, 'sha256': sha(path)} for path in (model_report, notes)]
        report['phase'] = 'complete'
        report['verified_sha256'] = True
        report['file_count'] = len(report['files'])
        report['bytes'] = sum(record['bytes'] for record in report['files'])
        report['sqlite_snapshots'] = sum(record['kind'] == 'sqlite_online_backup' for record in report['files'])
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({key: report[key] for key in ('phase', 'path', 'file_count', 'bytes', 'sqlite_snapshots', 'verified_sha256', 'processes_interrupted')}, ensure_ascii=False), flush=True)
    except Exception as error:
        report['phase'] = 'failed'
        report['errors'].append(str(error))
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        raise


if __name__ == '__main__':
    main()
