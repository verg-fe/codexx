"""Persistent, editable local skills and UTF-8 tools for the local assistant."""
from contextlib import contextmanager
from datetime import datetime, timezone
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import uuid

DEFAULT_ROOT = Path(os.environ.get('LOCAL_CODEX_ROOT', r'D:\LocalCodex'))


def read_local_text(path):
    data = Path(path).read_bytes()
    if data.startswith((b'\xff\xfe', b'\xfe\xff')):
        return data.decode('utf-16'), 'utf-16'
    if b'\x00' in data:
        raise ValueError('文件包含二进制数据，请使用二进制文件工具。')
    try:
        return data.decode('utf-8-sig'), 'utf-8'
    except UnicodeDecodeError:
        return data.decode('gb18030'), 'gb18030'


def atomic_text(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        temporary.write_bytes(text.encode('utf-8'))
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def parse_skill(text):
    match = re.match(r'\A---\r?\n(.*?)\r?\n---\r?\n?(.*)\Z', text, re.S)
    if not match:
        raise ValueError('技能缺少 YAML frontmatter。')
    header, body = match.groups()
    description = re.search(r'^description:\s*(.+)$', header, re.M)
    if not description:
        raise ValueError('技能缺少 description。')
    value = description.group(1).strip()
    if value.startswith('"'):
        value = json.loads(value)
    return value, body.lstrip('\r\n')


class SkillMemory:
    def __init__(self, root=DEFAULT_ROOT):
        self.root = Path(root)
        self.skills = self.root / 'codex-home' / 'skills'
        self.skills.mkdir(parents=True, exist_ok=True)
        bundled = Path(getattr(sys, '_MEIPASS', Path(__file__).parent)) / 'skills'
        self.bundled_skills = bundled.resolve()

    def path(self, name):
        if not isinstance(name, str) or not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', name) or len(name) > 63:
            raise ValueError('技能名称使用小写英文、数字和连字符，最多 63 字符。')
        directory = self.skills / name
        if not directory.resolve().is_relative_to(self.skills.resolve()):
            raise ValueError('技能目录不能链接到技能库外。')
        path = directory / 'SKILL.md'
        if not path.resolve().is_relative_to(self.skills.resolve()):
            raise ValueError('技能文件不能链接到技能库外。')
        return path

    @contextmanager
    def locked(self):
        with (self.skills / '.write.lock').open('a+b') as handle:
            handle.seek(0, 2)
            if handle.tell() == 0:
                handle.write(b'0')
                handle.flush()
            deadline = time.monotonic() + 8
            while True:
                try:
                    handle.seek(0)
                    if os.name == 'nt':
                        import msvcrt
                        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except (OSError, BlockingIOError):
                    if time.monotonic() > deadline:
                        raise ValueError('技能库正在写入，请稍后重试。')
                    time.sleep(0.05)
            try:
                yield
            finally:
                handle.seek(0)
                if os.name == 'nt':
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _read(self, name):
        user_path = self.path(name)
        path = user_path if user_path.is_file() else self.bundled_skills / name / 'SKILL.md'
        if not path.resolve().is_relative_to(self.bundled_skills) and not path.resolve().is_relative_to(self.skills.resolve()):
            raise ValueError('技能路径必须位于用户技能库或程序内置技能库。')
        if not path.is_file():
            raise FileNotFoundError('找不到该技能。')
        text, encoding = read_local_text(path)
        description, body = parse_skill(text)
        metadata_path = path.parent / 'local-resources.json'
        metadata = json.loads(metadata_path.read_text(encoding='utf-8-sig')) if metadata_path.is_file() else {}
        return {'name': name, 'description': description, 'body': body,
                'path': str(path), 'revision': hashlib.sha256(path.read_bytes()).hexdigest(),
                'encoding': encoding, 'resources': metadata.get('resources', []),
                'evidence': metadata.get('evidence', ''), 'updated_at': metadata.get('updated_at')}

    @staticmethod
    def resource_state(resource):
        path = Path(resource['path'])
        missing = []
        for relative in resource.get('check_files', []):
            check = path / relative
            if not check.resolve().is_relative_to(path.resolve()):
                raise ValueError('check_files 必须位于资源目录内。')
            if not check.exists():
                missing.append(relative)
        return {**resource, 'exists': path.exists(), 'missing_files': missing,
                'available': path.exists() and not missing}

    def read(self, name, offset=0, max_chars=6000):
        if offset < 0 or not 1 <= max_chars <= 16000:
            raise ValueError('读取范围无效。')
        with self.locked():
            row = self._read(name)
        body = row['body']
        row.update(body=body[offset:offset + max_chars], offset=offset,
                   total_chars=len(body), next_offset=offset + max_chars if offset + max_chars < len(body) else None)
        row['resources'] = [self.resource_state(item) for item in row['resources']]
        return row

    def search(self, query='', limit=5):
        limit = max(1, min(int(limit), 10))
        query = str(query).casefold().strip()
        tokens = set(re.findall(r'[a-z0-9_.-]+', query))
        for word in re.findall(r'[\u3400-\u9fff]+', query):
            tokens.update(word[i:i + 2] for i in range(max(1, len(word) - 1)))
        rows = []
        with self.locked():
            names=set()
            for skill_root in (self.skills,self.bundled_skills):
                try:
                    names.update(directory.name for directory in skill_root.iterdir()
                                 if directory.is_dir() and not directory.name.startswith('.')
                                 and (directory/'SKILL.md').is_file())
                except OSError:
                    continue
            for name in sorted(names):
                try:
                    row = self._read(name)
                    label = (row['name'] + ' ' + row['description']).casefold()
                    body = row['body'].casefold()
                    score = sum(4 if term in label else 1 for term in tokens if term in label or term in body)
                    if not query or score:
                        rows.append({'name': row['name'], 'description': row['description'],
                                     'path': row['path'], 'revision': row['revision'], 'score': score})
                except (OSError, UnicodeError, ValueError):
                    continue
        rows.sort(key=lambda row: (-row['score'], row['name']))
        return {'skills': rows[:limit], 'matched': len(rows), 'directory': str(self.skills)}

    def save(self, name, description, body, expected_revision=None, resources=None, evidence=None):
        path = self.path(name)
        if not isinstance(description, str) or not description.strip() or len(description) > 800:
            raise ValueError('请提供最多 800 字符的具体触发描述。')
        if not isinstance(body, str) or not body.strip() or len(body) > 24000:
            raise ValueError('技能正文应为 1 至 24,000 字符的总结。')
        if '\x00' in body or '\ufffd' in body or '\ufffd' in description:
            raise ValueError('文本包含二进制或不可恢复的乱码，请先恢复正确原文。')
        if resources is not None:
            if not isinstance(resources, list) or len(resources) > 20:
                raise ValueError('资源清单最多 20 项。')
            for item in resources:
                if not isinstance(item, dict) or not isinstance(item.get('path'), str):
                    raise ValueError('资源需要本机 path。')
                self.resource_state(item)
        with self.locked():
            old = self._read(name) if path.is_file() else None
            if old and expected_revision != old['revision']:
                raise ValueError('技能已存在或被更新。先 skill_read 获取最新 revision，再合并保存。')
            if not old and expected_revision:
                raise ValueError('技能已不存在，不能使用旧 revision。')
            backup = None
            if old:
                backup = self.root / 'backups' / 'skills' / name / (datetime.now().strftime('%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:8])
                backup.mkdir(parents=True)
                shutil.copy2(path, backup / 'SKILL.md')
                metadata = path.parent / 'local-resources.json'
                if metadata.is_file():
                    shutil.copy2(metadata, backup / metadata.name)
            text = '---\nname: ' + name + '\ndescription: ' + json.dumps(description.strip(), ensure_ascii=False) + '\n---\n\n' + body.strip() + '\n'
            state = {'updated_at': datetime.now(timezone.utc).isoformat(),
                     'resources': resources if resources is not None else (old or {}).get('resources', []),
                     'evidence': evidence if evidence is not None else (old or {}).get('evidence', '')}
            atomic_text(path.parent / 'local-resources.json', json.dumps(state, ensure_ascii=False, indent=2))
            atomic_text(path, text)
            revision = hashlib.sha256(path.read_bytes()).hexdigest()
        return {'saved': True, 'name': name, 'path': str(path), 'revision': revision,
                'backup': str(backup) if backup else None, 'encoding': 'utf-8'}


def local_read_text(path, offset=0, max_chars=6000):
    if offset < 0 or not 1 <= max_chars <= 16000:
        raise ValueError('读取范围无效。')
    path = Path(path)
    if path.stat().st_size > 4 * 1024 * 1024:
        raise ValueError('文本文件超过 4 MB，请搜索或分段读取。')
    text, encoding = read_local_text(path)
    return {'path': str(path), 'encoding': encoding, 'text': text[offset:offset + max_chars],
            'total_chars': len(text), 'next_offset': offset + max_chars if offset + max_chars < len(text) else None}


def powershell_path(root=None):
    root = Path(root or DEFAULT_ROOT)
    config = root / 'tools' / 'powershell' / 'current.json'
    try:
        candidate = Path(json.loads(config.read_text(encoding='utf-8'))['path'])
        if candidate.is_file() and candidate.name.lower() == 'pwsh.exe':
            return candidate
    except (OSError, ValueError, KeyError, TypeError):
        pass
    found = shutil.which('pwsh.exe')
    if found:
        return Path(found)
    return Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32' / 'WindowsPowerShell' / 'v1.0' / 'powershell.exe'

def shell_environment(env, root=None):
    env = dict(env)
    # Keep the programming agent and its tool children on the verified Python
    # installation. This changes this process tree only, never Windows PATH.
    python = Path.home() / 'AppData/Local/Programs/Python/Python312'
    sdk = Path.home() / 'AppData/Local/VectorAndroidSdk/platform-tools'
    prepend = []
    if (python / 'python.exe').is_file():
        prepend.extend((str(python), str(python / 'Scripts')))
    if (sdk / 'adb.exe').is_file():
        prepend.append(str(sdk))
    github = Path(root or DEFAULT_ROOT) / 'github-upload-work/gh/bin'
    if (github / 'gh.exe').is_file():
        prepend.append(str(github))
    if prepend:
        env['PATH'] = os.pathsep.join(prepend) + os.pathsep + env.get('PATH', '')
    shell = powershell_path(root)
    if shell.name.lower() == 'pwsh.exe':
        env['PATH'] = str(shell.parent) + os.pathsep + env.get('PATH', '')
    env['PYTHONUTF8'] = '1'
    env['PYTHONIOENCODING'] = 'utf-8'
    return env


def local_run_utf8(command, cwd=None, timeout=60):
    if not isinstance(command, str) or not command.strip() or len(command) > 16000 or not 1 <= timeout <= 110:
        raise ValueError('命令参数无效；长任务使用原生 exec_command。')
    prefix = "$u=[System.Text.UTF8Encoding]::new($false); [Console]::InputEncoding=$u; [Console]::OutputEncoding=$u; $OutputEncoding=$u; $PSDefaultParameterValues['Get-Content:Encoding']='utf8'; $PSDefaultParameterValues['Set-Content:Encoding']='utf8'; "
    encoded = base64.b64encode((prefix + command).encode('utf-16-le')).decode('ascii')
    shell = powershell_path()
    env = shell_environment(os.environ)
    process = subprocess.Popen([str(shell), '-NoLogo', '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded],
                               cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    timed_out = False
    try:
        out, err = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        subprocess.run(['taskkill.exe', '/PID', str(process.pid), '/T', '/F'],
                       capture_output=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), timeout=10)
        if process.poll() is None:
            process.kill()
        out, err = process.communicate(timeout=10)
    def decode(data):
        try:
            return data.decode('utf-8-sig')
        except UnicodeDecodeError:
            try:
                return data.decode('gb18030')
            except UnicodeDecodeError:
                return data.decode('utf-8', errors='replace')
    return {'exit_code': process.returncode, 'timed_out': timed_out,
            'stdout': decode(out)[:12000], 'stderr': decode(err)[:6000],
            'shell': str(shell), 'truncated': len(out) > 12000 or len(err) > 6000}


def schema(name, description, properties, required):
    annotations = {'readOnlyHint': name in ('skill_search', 'skill_read', 'local_read_text'),
                   'destructiveHint': name == 'local_run_utf8',
                   'idempotentHint': name in ('skill_search', 'skill_read', 'local_read_text'),
                   'openWorldHint': name == 'local_run_utf8'}
    return {'name': name, 'description': description, 'annotations': annotations, 'inputSchema': {'type': 'object', 'properties': properties,
            'required': required, 'additionalProperties': False}}


TOOLS = [
    schema('skill_search', 'Search persistent skills from earlier conversations before downloading dependencies or repeating solved setup. Empty query lists skills. Saved updates are visible immediately.',
           {'query': {'type': 'string'}, 'limit': {'type': 'integer', 'minimum': 1, 'maximum': 10}}, []),
    schema('skill_read', 'Read a skill in correct Chinese UTF-8, its latest revision, and whether recorded local tools still exist. Use revision when updating the skill.',
           {'name': {'type': 'string'}, 'offset': {'type': 'integer', 'minimum': 0}, 'max_chars': {'type': 'integer', 'minimum': 1, 'maximum': 16000}}, ['name']),
    schema('skill_save', 'Create or update your reusable skill at any time after learning useful facts. Write a concise method and verified local resource paths. Existing skills require their latest expected_revision. Updates are backed up. Do not store raw conversation logs or credentials.',
           {'name': {'type': 'string'}, 'description': {'type': 'string', 'maxLength': 800}, 'body': {'type': 'string', 'maxLength': 24000},
            'expected_revision': {'type': 'string'}, 'evidence': {'type': 'string'},
            'resources': {'type': 'array', 'maxItems': 20, 'items': {'type': 'object', 'properties': {
                'name': {'type': 'string'}, 'path': {'type': 'string'}, 'version': {'type': 'string'},
                'check_files': {'type': 'array', 'items': {'type': 'string'}}}, 'required': ['path'], 'additionalProperties': False}}},
           ['name', 'description', 'body']),
    schema('local_read_text', 'Read local UTF-8, UTF-16 BOM or GB18030 text without the Windows PowerShell Chinese encoding problem. Returns source encoding. Not for binary files.',
           {'path': {'type': 'string'}, 'offset': {'type': 'integer', 'minimum': 0}, 'max_chars': {'type': 'integer', 'minimum': 1, 'maximum': 16000}}, ['path']),
    schema('local_run_utf8', 'Run a short PowerShell text command with UTF-8 input/output and UTF-8 Get-Content defaults. Useful for Chinese output. Not for binary screenshots or long/background jobs; those use native exec_command and Python byte capture.',
           {'command': {'type': 'string', 'maxLength': 16000}, 'cwd': {'type': 'string'}, 'timeout': {'type': 'integer', 'minimum': 1, 'maximum': 110}}, ['command']),
]


def call_tool(root, name, arguments):
    memory = SkillMemory(root)
    handlers = {'skill_search': memory.search, 'skill_read': memory.read, 'skill_save': memory.save,
                'local_read_text': local_read_text, 'local_run_utf8': local_run_utf8}
    if name not in handlers:
        raise ValueError('Unknown local skill tool')
    return handlers[name](**arguments)


INSTRUCTIONS = '''\n技能按需使用：只搜索并读取与当前任务直接相关的技能，不注入完整目录。复用前核对技能路径和版本；执行安装或配置时保留回退并验证实际结果。写入技能时保存简明步骤、路径、版本和证据，合并到现有技能并标出未验证内容。\n'''


def install_bundled_skills(root, bundle):
    source = Path(bundle) / 'skills'
    target = Path(root) / 'codex-home' / 'skills'
    target.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        for skill in source.iterdir():
            if skill.is_dir() and not (target / skill.name).exists():
                shutil.copytree(skill, target / skill.name)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', default=str(DEFAULT_ROOT))
    parser.add_argument('action', choices=['search', 'read', 'save'])
    parser.add_argument('value', nargs='?', default='')
    args = parser.parse_args()
    memory = SkillMemory(args.root)
    if args.action == 'save':
        result = memory.save(**json.loads(Path(args.value).read_text(encoding='utf-8-sig')))
    elif args.action == 'read':
        result = memory.read(args.value)
    else:
        result = memory.search(args.value)
    sys.stdout.buffer.write(json.dumps(result, ensure_ascii=False).encode('utf-8') + b'\n')
