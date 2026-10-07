"""Prepare source, verified release archives, and a redacted backup for private upload."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import zipfile

WORKSPACE = Path(__file__).resolve().parent
SOURCE = WORKSPACE / 'release36'
ROOT = Path(r'D:\LocalCodex')
WORK = ROOT / 'github-upload-work'
REPO = WORK / 'repo'
ASSETS = WORK / 'assets'
BACKUP = Path(r'C:\my_projects\MyCodex-v35-backup-20261007-104748')
APP = ROOT / 'app' / 'MyCodex-proxy36'
SKIP_DIRS = {'__pycache__', '.git', 'build', 'dist', 'node_modules', '.pytest_cache', '.venv', 'venv', '.tmp', 'thread-writer-locks'}
TEXT_SUFFIXES = {'.py', '.ps1', '.cmd', '.bat', '.sh', '.txt', '.md', '.json', '.jsonl', '.toml', '.yaml', '.yml', '.xml', '.ini', '.cfg', '.log', '.js', '.ts', '.html', '.css', '.svg', '.spec', '.csv', '.sql', '.properties'}
FIELDS = re.compile(r'''(?i)(["']?(?:api_key|access_token|refresh_token|id_token|client_secret|password|OPENAI_API_KEY)["']?\s*[:=]\s*["'])([^"'\r\n]{8,512})(["'])''')
TOKENS = re.compile(r'\b(?:github_pat_[A-Za-z0-9_]{30,}|gh[pousr]_[A-Za-z0-9_]{25,}|sk-(?:proj-)?[A-Za-z0-9_-]{25,})\b')
PRIVATE_NAMES = {'auth.json', 'credentials.json', 'credentials', '.env', '.netrc', '.git-credentials', 'hosts.yml', 'proxy-settings.json', 'id_rsa', 'id_ed25519'}
audit = {'excluded_credentials': [], 'redacted_files': [], 'archive_files': {}, 'errors': []}
secrets = set()


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def walk(root):
    for folder, dirs, names in os.walk(root, followlinks=False):
        dirs[:] = [name for name in dirs if name not in SKIP_DIRS and not (Path(folder) / name).is_symlink()]
        for name in sorted(names):
            path = Path(folder) / name
            if not path.is_symlink():
                yield path


def credential_file(path):
    name = path.name.lower()
    return name in PRIVATE_NAMES or name.startswith('.env.') or name.endswith(('.pem', '.p12', '.pfx', '.key')) or name.startswith('codex-proxy-')


def decode(raw):
    encoding = 'utf-16' if raw.startswith((b'\xff\xfe', b'\xfe\xff')) else 'utf-8-sig' if raw.startswith(b'\xef\xbb\xbf') else 'utf-8'
    try:
        return raw.decode(encoding), encoding
    except UnicodeDecodeError:
        return None, None


def is_text(path):
    return path.suffix.lower() in TEXT_SUFFIXES or path.name.lower() in {'license', 'notice', 'readme', 'config'}


def collect_secrets(paths):
    for path in paths:
        if not path.is_file() or path.stat().st_size > 16 * 1024 ** 2 or not is_text(path):
            continue
        text, _ = decode(path.read_bytes())
        if text is None:
            continue
        for match in FIELDS.finditer(text):
            value = match[2]
            if value.startswith(('__', '<', '$', 'your', 'YOUR', 'REPLACE', 'example', 'test-', 'dummy')):
                continue
            if '\\' in value or '{' in value or len(value.split()) > 2:
                continue
            secrets.add(value)
        secrets.update(TOKENS.findall(text))
    proxy = json.loads((ROOT / 'proxy-settings.json').read_text(encoding='utf-8'))
    if proxy.get('uuid'):
        secrets.add(proxy['uuid'])


def redact(text):
    for value in sorted(secrets, key=len, reverse=True):
        text = text.replace(value, '__REDACTED__')
    return TOKENS.sub('__REDACTED__', text)


def sanitized_file(path):
    if credential_file(path):
        audit['excluded_credentials'].append(str(path))
        return None
    if is_text(path) and path.stat().st_size <= 128 * 1024 ** 2:
        raw = path.read_bytes()
        text, encoding = decode(raw)
        if text is not None:
            clean = redact(text)
            if clean != text:
                audit['redacted_files'].append(str(path))
                target = WORK / 'sanitized' / hashlib.sha256(str(path).encode()).hexdigest() / path.name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(clean.encode(encoding))
                return target
    with path.open('rb') as stream:
        sqlite = stream.read(16) == b'SQLite format 3\0'
    if sqlite:
        return sanitize_database(path)
    return path


def quote(name):
    return '"' + name.replace('"', '""') + '"'


def sanitize_database(path):
    target = WORK / 'sanitized' / hashlib.sha256(str(path).encode()).hexdigest() / path.name
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, target)
    changed = 0
    with sqlite3.connect(target) as db:
        tables = db.execute("SELECT name,sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()
        virtual = [name for name, sql in tables if sql and 'CREATE VIRTUAL TABLE' in sql.upper()]
        for name, sql in tables:
            if name in virtual or any(name.startswith(prefix + '_') and not name.endswith('_content') for prefix in virtual):
                continue
            try:
                reader = db.execute('SELECT rowid AS __upload_rowid__, * FROM ' + quote(name))
            except sqlite3.OperationalError:
                continue
            columns = [column[0] for column in reader.description][1:]
            while rows := reader.fetchmany(200):
                for row in rows:
                    replacements = []
                    values = []
                    for column, value in zip(columns, row[1:]):
                        if isinstance(value, str):
                            clean = redact(value)
                            if clean != value:
                                replacements.append(quote(column) + '=?')
                                values.append(clean)
                    if replacements:
                        db.execute('UPDATE ' + quote(name) + ' SET ' + ','.join(replacements) + ' WHERE rowid=?', values + [row[0]])
                        changed += 1
        if changed:
            for name in virtual:
                try:
                    db.execute('INSERT INTO ' + quote(name) + '(' + quote(name) + ") VALUES('rebuild')")
                except sqlite3.OperationalError:
                    pass
            db.commit()
            db.execute('VACUUM')
        if db.execute('PRAGMA quick_check').fetchall() != [('ok',)]:
            raise RuntimeError('Sanitized database integrity failed: ' + str(path))
    if changed:
        audit['redacted_files'].append(str(path))
    # Exclude any database that still embeds a known credential in a non-text record.
    raw = target.read_bytes()
    if any(value.encode('utf-8') in raw for value in secrets):
        audit['excluded_credentials'].append(str(path) + ' [credential in binary database record]')
        return None
    return target


def write_archive(name, paths, root):
    destination = ASSETS / name
    count = 0
    total = 0
    with zipfile.ZipFile(destination, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=3, allowZip64=True) as archive:
        for original in paths:
            source = sanitized_file(original)
            if source is None:
                continue
            arcname = original.relative_to(root).as_posix()
            info = zipfile.ZipInfo.from_file(source, arcname)
            info.compress_type = zipfile.ZIP_DEFLATED
            info._compresslevel = 3
            size = source.stat().st_size
            # Read only the byte range in the snapshot, so appending live logs cannot make the archive unbounded.
            with source.open('rb') as incoming, archive.open(info, 'w', force_zip64=size >= 2 ** 31) as outgoing:
                remaining = size
                while remaining:
                    chunk = incoming.read(min(4 * 1024 ** 2, remaining))
                    if not chunk:
                        raise RuntimeError('File shrank during packaging: ' + str(original))
                    outgoing.write(chunk)
                    remaining -= len(chunk)
            count += 1
            total += size
            if count % 500 == 0:
                print(json.dumps({'archive': name, 'files': count, 'input_bytes': total}), flush=True)
    audit['archive_files'][name] = {'files': count, 'input_bytes': total, 'bytes': destination.stat().st_size, 'sha256': digest(destination)}
    print(json.dumps({'archive_complete': name, **audit['archive_files'][name]}), flush=True)
    return destination


def split_archive(path, maximum=512 * 1024 ** 2):
    if path.stat().st_size <= maximum:
        return [path]
    parts = []
    with path.open('rb') as source:
        number = 1
        while first := source.read(min(4 * 1024 ** 2, maximum)):
            target = path.with_name(path.name + f'.part{number:03d}')
            with target.open('wb') as stream:
                stream.write(first)
                size = len(first)
                while size < maximum:
                    chunk = source.read(min(4 * 1024 ** 2, maximum - size))
                    if not chunk:
                        break
                    stream.write(chunk)
                    size += len(chunk)
            parts.append(target)
            number += 1
    return parts


def make_repo(workspace_files):
    REPO.mkdir(exist_ok=False)
    for path in workspace_files:
        if path.is_relative_to(SOURCE):
            target = REPO / 'src' / path.relative_to(SOURCE)
            if path.parent == SOURCE / 'tools' and path.suffix.lower() in {'.exe', '.dll'}:
                continue
        elif path.parent == WORKSPACE and path.suffix.lower() in {'.py', '.ps1', '.md', '.spec', '.svg'}:
            target = REPO / 'legacy-workbench' / path.name
        else:
            continue
        if path.stat().st_size > 10 * 1024 ** 2:
            continue
        clean = sanitized_file(path)
        if clean:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(clean, target)
    docs = REPO / 'docs'
    docs.mkdir()
    for name in ('日志改进与使用说明-v36.md', 'deployment-proxy36.json'):
        clean = sanitized_file(ROOT / name)
        shutil.copy2(clean, docs / name)
    checks = REPO / 'verification'
    checks.mkdir()
    for path in ROOT.glob('verification-proxy36-*.json'):
        clean = sanitized_file(path)
        if clean:
            shutil.copy2(clean, checks / path.name)
    config = REPO / 'config'
    config.mkdir()
    example = {'enabled': False, 'server': 'YOUR_SERVER', 'port': 443, 'ws_path': '/connect', 'sni': 'YOUR_SERVER', 'ws_host': 'YOUR_SERVER', 'uuid': ''}
    (config / 'proxy-settings.example.json').write_text(json.dumps(example, indent=2), encoding='utf-8')
    (REPO / '.gitignore').write_text('__pycache__/\n*.py[cod]\nbuild/\ndist/\nnode_modules/\n.env*\nauth.json\nproxy-settings.json\n*.gguf\n*.exe\n*.dll\n*.zip\n*.part[0-9]*\n*.pid\n*.lock\n', encoding='utf-8')
    (REPO / 'README.md').write_text('''# codexx / 我的 Codex v36

Windows 本地编程工作台：Qwen 本地模型、项目文件、对话历史、原生工具调用、网页资料搜索。

## 最新版本

- 当前维护源码在 `src/`。`legacy-workbench/` 保存以前的部署、诊断与升级资料。
- v36 新增代理一键开关、自定义模型目录、搜索与网页读取工具。
- PowerShell 报错即使返回码为 0 也保留失败证据；提示写成文字而没有执行的工具调用；压缩后保留最近用户纠正。
- [详细使用说明及最近日志分析](docs/日志改进与使用说明-v36.md)。
- [验证记录](verification/)。检查工具实际联网与引擎工具发现，不保证模型每次都主动选择搜索。

## 下载完整文件

仓库的 `v36-20261007` Release 附件提供：

1. `MyCodex-v36-windows.zip`：已打包的新版程序和代理组件。
2. `codexx-workspace-v36.zip`：完整工作目录快照，包含子项目与工具文件，排除构建缓存、凭据和模型权重。
3. `MyCodex-v35-backup-redacted.zip` 或其 `.partNNN` 分卷：升级前完整版本快照，约 6 GB 原始数据，含运行组件、源码、配置、对话、日志及数据库；已知凭据脱敏。
4. `runtime-moe4all.zip`：旧备份若缺少此后端，则单独提供现有运行组件。
5. `current-v36-config-and-reports.zip`：当前设置、启动入口及报告；代理身份凭据与 API 密钥需重新填写。
6. `release-assets-manifest.json`：文件大小及 SHA256；分卷合并后也能校验完整压缩包。

分卷按编号顺序拼接，用附件 `join_release_parts.py` 合并。原始本机备份保持不变；上传副本经过凭据脱敏，原有校验清单代表脱敏前文件，上传文件请以新清单为准。

## 安装与源码运行

原环境为 Windows、AMD RX 9070，工作台目录 `D:\\LocalCodex`、模型目录 `G:\\LocalCodex\\models`。

- 恢复备份 `deployment/` 中需要的引擎、运行时、模板和配置到 `D:\\LocalCodex`；不要运行旧升级脚本覆盖新版。
- 将新版程序解压至 `D:\\LocalCodex\\app\\MyCodex-proxy36`，启动 `MyCodex.exe --no-auto-model --show-model-options`。
- GGUF 权重未上传；放入自选目录，在“模型与性能”里选择目录后启动模型。
- `config/proxy-settings.example.json` 是代理配置模板。真实 UUID、API 密钥及账号登录凭据未上传，应在本机重新配置。
- 从源码打包可使用 `src/MyCodex.spec`；先将官方 sing-box Windows 组件放入 `src/tools/`。代理组件和第三方组件的许可见对应包内 LICENSE。

官方资料：[Codex MCP](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)、[sing-box VLESS](https://sing-box.sagernet.org/configuration/outbound/vless/)、[sing-box v1.14.2](https://github.com/SagerNet/sing-box/releases/tag/v1.14.2)。

此仓库按私有仓库创建。上传过程不会关闭当前工作台或模型任务。
''', encoding='utf-8')


def main():
    WORK.mkdir(exist_ok=True)
    ASSETS.mkdir(exist_ok=True)
    workspace_files = list(walk(WORKSPACE))
    backup_files = list(walk(BACKUP))
    app_files = list(walk(APP))
    current_files = [path for path in ROOT.iterdir() if path.is_file() and not path.name.endswith(('.pid', '.lock'))]
    collect_secrets(workspace_files + backup_files + current_files)
    print(json.dumps({'phase': 'credentials inventoried', 'known_secret_values': len(secrets), 'workspace_files': len(workspace_files), 'backup_files': len(backup_files)}), flush=True)
    make_repo(workspace_files)
    archives = [write_archive('MyCodex-v36-windows.zip', app_files, APP),
        write_archive('codexx-workspace-v36.zip', workspace_files, WORKSPACE),
        write_archive('current-v36-config-and-reports.zip', current_files, ROOT),
        write_archive('MyCodex-v35-backup-redacted.zip', backup_files, BACKUP)]
    if (ROOT / 'runtime-moe4all').exists() and not (BACKUP / 'deployment' / 'runtime-moe4all').exists():
        archives.append(write_archive('runtime-moe4all.zip', list(walk(ROOT / 'runtime-moe4all')), ROOT / 'runtime-moe4all'))
    assets = []
    for archive in archives:
        parts = split_archive(archive)
        for part in parts:
            assets.append({'name': part.name, 'bytes': part.stat().st_size, 'sha256': digest(part), 'archive': archive.name})
    manifest = {'repo': 'verg-fe/codexx', 'private_required': True, 'tag': 'v36-20261007',
        'created_at': datetime.now(timezone.utc).isoformat(), 'assets': assets, 'archives': audit['archive_files'],
        'models_included': False, 'credentials_redacted': True, 'local_backup_modified': False}
    (ASSETS / 'release-assets-manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    (REPO / 'docs' / 'release-assets-manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    # The detailed path list stays local; cloud audit includes counts only.
    (WORK / 'upload-audit-private.json').write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding='utf-8')
    public_audit = {'known_secret_values_redacted': len(secrets), 'redacted_files': len(set(audit['redacted_files'])),
        'credential_files_excluded': len(set(audit['excluded_credentials'])), 'models_included': False,
        'original_backup_modified': False, 'archives': audit['archive_files']}
    (REPO / 'docs' / 'upload-audit.json').write_text(json.dumps(public_audit, indent=2), encoding='utf-8')
    # Verify every source payload that will enter Git for known credentials.
    residual = []
    for path in walk(REPO):
        raw = path.read_bytes()
        if any(value.encode('utf-8') in raw for value in secrets):
            residual.append(str(path.relative_to(REPO)))
    if residual:
        raise RuntimeError('Credential scan found remaining values in: ' + ', '.join(residual[:10]))
    (WORK / 'upload-prepared.json').write_text(json.dumps({'ready': True, 'repository': str(REPO), 'assets': assets,
        'public_audit': public_audit}, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'ready': True, 'repository': str(REPO), 'assets': len(assets), 'total_upload_bytes': sum(item['bytes'] for item in assets),
        'redacted_files': public_audit['redacted_files'], 'credential_files_excluded': public_audit['credential_files_excluded']}), flush=True)


if __name__ == '__main__':
    main()
