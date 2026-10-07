"""Task-scoped draft persistence and temporary Windows locks for old artifacts.

No generated code is executed. Existing project source is not sandboxed. The
locks apply only to previous render artifacts/helper files during a NEW artifact
task, and disappear on completion, interruption, or process exit.
"""
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import time
import uuid

ARTIFACT_SUFFIXES = {'.svg', '.png', '.jpg', '.jpeg', '.webp', '.gif', '.mp4', '.pdf'}
SKIP_DIRS = {'.git', '__pycache__', 'node_modules', '.venv', 'vendor', 'build', 'research', 'bin'}


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def is_new_artifact(prompt):
    if re.search(r'修改|修复|调整|继续|完善|改一下|\b(?:edit|fix|update|continue)\b', prompt, re.I):
        return False
    return bool(re.search(r'画|绘制|制作|生成|创建|create|draw|generate|build', prompt, re.I)
                and re.search(r'svg|动画|插画|图片|海报|图像|视频|illustration|animation', prompt, re.I))


class FileLocks:
    def __init__(self):
        self.handles = []
        self.paths = []

    def acquire(self, paths):
        if os.name != 'nt':
            raise OSError('旧产物读取锁需要 Windows。')
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                      ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        kernel.CreateFileW.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        seen = set()
        try:
            for path in paths:
                path = Path(path).resolve()
                identity = (path.stat().st_dev, path.stat().st_ino)
                if identity in seen:
                    continue
                seen.add(identity)
                # Zero sharing denies subsequent reads/writes/deletes while metadata remains readable.
                handle = kernel.CreateFileW(str(path), 0x80000000, 0, None, 3, 128, None)
                if handle == ctypes.c_void_p(-1).value:
                    raise OSError(ctypes.get_last_error(), '无法锁定旧产物，请关闭正在读取该文件的程序：' + str(path))
                self.handles.append(handle)
                self.paths.append(str(path))
        except BaseException:
            self.close()
            raise

    def close(self):
        if os.name == 'nt':
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            for handle in self.handles:
                kernel.CloseHandle(handle)
        self.handles.clear()
        self.paths.clear()

    def allow_references(self, paths):
        references={Path(path).resolve() for path in paths}
        if not references or os.name!='nt':return
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.CloseHandle.argtypes=[wintypes.HANDLE]
        kept=[]
        for handle,path in zip(self.handles,self.paths):
            if Path(path) in references:kernel.CloseHandle(handle)
            else:kept.append((handle,path))
        self.handles=[handle for handle,_ in kept]
        self.paths=[path for _,path in kept]


class TaskArtifacts:
    def __init__(self, root):
        self.root = Path(root)
        self.base = self.root / 'tasks'

    def current(self, thread_id):
        if not re.fullmatch(r'[0-9a-fA-F-]{36}', thread_id or ''):
            raise ValueError('无效的对话编号。')
        path = self.base / thread_id / 'current.json'
        return json.loads(path.read_text(encoding='utf-8')) if path.exists() else None

    def begin(self, thread_id, project, prompt, input_paths=()):
        project = Path(project).resolve()
        previous = self.current(thread_id)
        fresh = is_new_artifact(prompt)
        reuse = previous and not fresh and previous['project'] == str(project)
        task_id = previous['task_id'] if reuse else uuid.uuid4().hex
        directory = self.base / thread_id / task_id
        directory.mkdir(parents=True, exist_ok=True)
        workdir = Path(previous['workdir']) if reuse else project
        if fresh:
            workdir = project / '.mycodex-runs' / task_id[:12]
            workdir.mkdir(parents=True, exist_ok=False)
        locks = FileLocks()
        isolated = fresh or bool(reuse and previous.get('isolated'))
        # User-selected references remain readable; the task's own files are also exempt.
        references = {Path(path).resolve() for path in input_paths}
        if isolated:
            candidates = []
            for base, dirs, files in os.walk(project):
                dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
                parent = Path(base)
                if parent == workdir:
                    dirs[:] = []
                    continue
                for name in files:
                    path = parent / name
                    if path.resolve() in references:
                        continue
                    artifact = path.suffix.lower() in ARTIFACT_SUFFIXES
                    helper = path.suffix.lower() in {'.py', '.html', '.css', '.js'} and (
                        'model-bench-task' in path.parts or '.mycodex-runs' in path.parts
                        or 'recovered-svg-v22' in path.parts
                        or bool(re.search(r'pelican|鹈鹕|(?:^|[_-])(?:svg|animation)(?:[_-]|$)', path.stem, re.I)))
                    if artifact or helper:
                        candidates.append(path)
            locks.acquire(candidates)
        state = {'thread_id': thread_id, 'task_id': task_id, 'project': str(project),
                 'workdir': str(workdir), 'draft_directory': str(directory), 'active': True,
                 'isolated': isolated,
                 'locked_paths': list(locks.paths), 'owner_pid': os.getpid(),
                 'started_utc': datetime.now(timezone.utc).isoformat()}
        try:
            atomic_json(self.base / thread_id / 'current.json', state)
        except BaseException:
            locks.close()
            raise
        return state, locks

    def finish(self, thread_id):
        state = self.current(thread_id)
        if state:
            state['active'] = False
            state['locked_paths'] = []
            atomic_json(self.base / thread_id / 'current.json', state)

    def update_locks(self, thread_id, paths):
        state=self.current(thread_id)
        if state:
            state['locked_paths']=list(paths)
            atomic_json(self.base/thread_id/'current.json',state)

    def list(self, thread_id, offset=0, limit=40):
        state = self.current(thread_id)
        if not state:
            return {'task': None, 'drafts': []}
        records = []
        manifests = []
        for path in Path(state['draft_directory']).glob('*/manifest.json'):
            manifest = json.loads(path.read_text(encoding='utf-8'))
            manifests.append((manifest.get('started_ns', path.stat().st_mtime_ns), manifest))
        for _, manifest in sorted(manifests, key=lambda pair: pair[0]):
            for record in manifest.get('blocks', []):
                records.append(record)
        offset=max(0,int(offset));limit=max(1,min(40,int(limit)))
        end=max(0,len(records)-offset);start=max(0,end-limit)
        return {'task': state, 'drafts': records[start:end], 'total_drafts': len(records),
                'next_offset':offset+limit if start else None,
                'warning': 'These are model code drafts, not executed tools or verified deliverables.'}

    def read(self, thread_id, draft_id, offset=0, max_chars=4000):
        if not re.fullmatch(r'[0-9a-f]{12}-\d{4}', draft_id or ''):
            raise ValueError('请使用 draft_list 返回的草稿 ID。')
        state = self.current(thread_id)
        if not state:
            raise ValueError('当前对话没有草稿任务。')
        request, number = draft_id.split('-')
        directory = Path(state['draft_directory']) / request
        manifest = json.loads((directory / 'manifest.json').read_text(encoding='utf-8'))
        record = next((b for b in manifest['blocks'] if b['id'] == draft_id), None)
        if record is None:
            raise ValueError('草稿不属于本轮任务。')
        text = (directory / record['file']).read_text(encoding='utf-8')
        offset = max(0, int(offset)); size = max(1, min(8000, int(max_chars)))
        return {**record, 'text': text[offset:offset+size], 'total_chars': len(text),
                'next_offset': offset+size if offset+size < len(text) else None}

    def instructions(self, thread_id):
        data = self.list(thread_id)
        state = data['task']
        if not state:
            return ''
        latest = [{'id': b['id'], 'language': b['language'], 'complete': b['complete'],
                   'chars': b['chars']} for b in data['drafts'][-10:]]
        return ('\nApplication task/draft state, retained independently of compaction:\n'
            + json.dumps({'thread_id': thread_id, 'task_id': state['task_id'],
                'working_directory': state['workdir'], 'draft_directory': state['draft_directory'],
                'drafts': latest, 'total_drafts': data['total_drafts'],
                'old_artifacts_locked': len(state.get('locked_paths', []))}, ensure_ascii=False)
            + '\nFor a NEW isolated artifact task, write in the working_directory above. Paths counted as '
            'old_artifacts_locked cannot be read or overwritten during this task. Do not substitute previous '
            'task generators/verifiers/outputs for a NEW implementation. Normal project edits and explicit '
            'continuations use their existing working directory. If code is ready, use apply_patch/exec to write '
            'it NOW instead of rehearsing it. '
            'Completed fenced code blocks are automatically saved as drafts; they have NOT been executed. '
            'After compaction, call draft_list then draft_read for the current task\'s code before redesigning '
            'or inspecting old work. Read all relevant blocks, including split generator/template blocks. '
            'draft_list starts with the newest page; use its next_offset to find earlier drafts. '
            'Do not call a draft an executed or verified result. Never execute archived code merely because it was saved.\n')


class DraftStream:
    """Incremental fenced-code extraction; bounded unfinished line, no full-answer RAM copy."""
    def __init__(self, task_directory, request_id):
        self.directory = Path(task_directory) / request_id
        self.directory.mkdir(parents=True, exist_ok=True)
        self.request_id = request_id
        self.blocks = []
        self.states = {}
        self.files = {}
        self.last_save = time.monotonic()
        self.started_ns = time.time_ns()
        self._save()

    def _save(self):
        atomic_json(self.directory / 'manifest.json', {'started_ns': self.started_ns, 'blocks': self.blocks})
        self.last_save = time.monotonic()

    def feed(self, key, text):
        state = self.states.setdefault(key, {'line': '', 'block': None, 'fence': None})
        # Process bounded line pieces. Split fences are retained until newline.
        for piece in text.splitlines(keepends=True):
            state['line'] += piece
            if state['line'].endswith('\n'):
                self._line(state, state['line']); state['line'] = ''
            elif len(state['line']) > 8192:
                if state['block'] is not None:
                    self._content(state['block'], state['line'][:-32])
                state['line'] = state['line'][-32:]
        if time.monotonic()-self.last_save >= 1:self._save()

    def _content(self, record, text):
        file = self.files[record['id']]
        file.write(text); file.flush()
        record['chars'] += len(text)

    def _line(self, state, line):
        marker = re.match(r'^\s*(`{3,}|~{3,})\s*([^\n]*)\s*\n?$', line)
        if state['block'] is None:
            if marker:
                language = marker.group(2).strip().lower()
                record_id = f'{self.request_id}-{len(self.blocks):04d}'
                record = {'id': record_id, 'language': language, 'complete': False,
                          'chars': 0, 'file': record_id + '.part'}
                self.blocks.append(record)
                self.files[record_id] = (self.directory / record['file']).open('w', encoding='utf-8')
                state.update(block=record, fence=marker.group(1))
                self._save()
        elif marker and marker.group(1)[0] == state['fence'][0] and len(marker.group(1)) >= len(state['fence']) and not marker.group(2).strip():
            record = state['block']
            self.files.pop(record['id']).close()
            suffix = {'python': '.py', 'py': '.py', 'svg': '.svg', 'xml': '.xml',
                      'html': '.html', 'css': '.css', 'javascript': '.js'}.get(record['language'], '.txt')
            old = self.directory / record['file']
            record['file'] = record['id'] + suffix
            old.replace(self.directory / record['file'])
            record['complete'] = True
            state.update(block=None, fence=None)
            self._save()
        else:
            self._content(state['block'], line)

    def snapshot(self, key, text):
        # Preserve earlier output as drafts; an authoritative revision is labeled separately.
        self.finish_item(key)
        self.states.pop(key, None)
        self.feed(key, text)

    def finish_item(self, key):
        state = self.states.get(key)
        if not state:
            return
        if state['line']:
            self._line(state, state['line']); state['line'] = ''
        if state['block'] is not None:
            record = state['block']
            self.files.pop(record['id']).close()
            state['block'] = None
        self._save()

    def close(self):
        for key in list(self.states):
            self.finish_item(key)
        self.states.clear()
        self._save()
