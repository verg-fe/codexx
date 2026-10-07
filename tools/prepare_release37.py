"""Preserve v36 and the stopped conversation before the v37 upgrade."""
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess

WORKSPACE = Path(__file__).resolve().parent
ROOT = Path(r'D:\LocalCodex')
STAMP = datetime.now(timezone(timedelta(hours=8))).strftime('%Y%m%d-%H%M%S')
BACKUP = Path(r'C:\my_projects') / ('MyCodex-v36-backup-' + STAMP)
RELEASE = WORKSPACE / 'release37'

def main():
    if RELEASE.exists():
        raise FileExistsError(RELEASE)
    BACKUP.mkdir()
    identity = subprocess.check_output(['whoami'], text=True).strip()
    subprocess.run(['icacls', str(BACKUP), '/inheritance:r', '/grant:r',
        identity + ':(OI)(CI)(F)', '*S-1-5-18:(OI)(CI)(F)'], check=True, capture_output=True)
    spec = importlib.util.spec_from_file_location('snapshot_helper', WORKSPACE / 'backup_current_codex.py')
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    groups = [(WORKSPACE / 'release36', BACKUP / 'source36'),
        (ROOT / 'app' / 'MyCodex-proxy36', BACKUP / 'app36'),
        (ROOT / 'conversations', BACKUP / 'conversations'),
        (ROOT / 'codex-home' / 'sessions', BACKUP / 'sessions'),
        (ROOT / 'logs' / 'generation', BACKUP / 'generation')]
    records = []
    excluded = []
    for origin, destination in groups:
        if origin.exists():
            for source, target in helper.inventory(origin, destination, excluded):
                row = helper.copy_snapshot(source, target)
                row['path'] = str(target.relative_to(BACKUP))
                records.append(row)
    for name in ('settings.json', 'proxy-settings.json', 'active-model.json', 'request-routing.json',
            'deployment-proxy36.json', 'github-upload-v36.json', 'generation-status.json'):
        source = ROOT / name
        if source.exists():
            row = helper.copy_snapshot(source, BACKUP / name)
            row['path'] = name
            records.append(row)
    shortcut = Path.home() / 'Desktop' / '我的Codex.cmd'
    shutil.copy2(shortcut, BACKUP / 'desktop-original.cmd')
    for row in records:
        if helper.sha(BACKUP / row['path']) != row['sha256']:
            raise RuntimeError('Snapshot checksum mismatch: ' + row['path'])
    report = {'version': 'v36', 'complete': True, 'path': str(BACKUP), 'files': records,
        'verified_sha256': True, 'bytes': sum(row['bytes'] for row in records),
        'models_copied': False, 'previous_full_runtime_backup': r'C:\my_projects\MyCodex-v35-backup-20261007-104748',
        'conversation_interrupted_at': '2026-10-07T12:44:17+08:00'}
    (BACKUP / 'backup-manifest.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    shutil.copytree(WORKSPACE / 'release36', RELEASE,
        ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    (ROOT / 'backup-before-v37.json').write_text(json.dumps({key: report[key] for key in
        ('version', 'complete', 'path', 'verified_sha256', 'bytes', 'models_copied')}, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'backup': str(BACKUP), 'bytes': report['bytes'], 'source': str(RELEASE), 'sha256_verified': True}, ensure_ascii=False))

if __name__ == '__main__':
    main()
