"""Versioned local GGUF catalog shared by the UI, gateway and worker tools."""
from collections.abc import Mapping
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import threading
import uuid

SCHEMA_VERSION = 1
MAX_CONTEXT = 276480


def _defaults(model_directory):
    rows = [
        ('Jack-3.8-27B-V2-VL-16GB-VRAM', 'Jack V2 · 27B VL', 12120033600, 40960, True, 'mmproj-Qwen3.8-27B-BF16.gguf'),
        ('Huihui-Qwen3.8-27B-abliterated-Q4_K', 'Huihui · Qwen3.8 27B Q4_K', 16810714400, 40960, True, 'mmproj-Qwen3.8-27B-BF16.gguf'),
        ('Huihui-Qwen3.8-27B-abliterated-GSQ-RCO-IQ3_S', 'Huihui · 27B IQ3_S · 11.77 GB · 视觉', 11771546208, 97280, True, 'mmproj-Qwen3.8-27B-BF16.gguf'),
    ]
    return {'schema_version': SCHEMA_VERSION, 'models': [
        {'id': name, 'display_name': label, 'provider': 'local', 'repo_id': None, 'revision': None,
         'filename': name + '.gguf', 'path': None, 'size_bytes': size, 'sha256': None,
         'architecture': None, 'quantization': name.rsplit('-', 1)[-1], 'context_limit': MAX_CONTEXT,
         'default_context': context, 'chat_template': None, 'supports_tools': True, 'vision': vision,
         'projector_filename': projector, 'runtime': 'llama-server', 'status': 'builtin'}
        for name, label, size, context, vision, projector in rows]}


class ModelCatalog(Mapping):
    def __init__(self, root, model_directory):
        self.root = Path(root)
        self.directory = Path(model_directory)
        self.path = self.root / 'model-catalog.json'
        self._lock = threading.RLock()
        self._mtime = None
        self._models = {}
        self.ensure()

    def ensure(self):
        self.root.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.write(_defaults(self.directory))
        else:
            try:
                data = json.loads(self.path.read_text(encoding='utf-8-sig'))
            except (OSError, ValueError):
                data = None
            if not isinstance(data, dict) or data.get('schema_version') != SCHEMA_VERSION or not isinstance(data.get('models'), list):
                legacy = self.root / ('model-catalog-legacy-' + datetime.now().strftime('%Y%m%d-%H%M%S') + '.json')
                os.replace(self.path, legacy)
                self.write(_defaults(self.directory))
        self.reload()

    def write(self, data):
        if data.get('schema_version') != SCHEMA_VERSION or not isinstance(data.get('models'), list):
            raise ValueError('模型目录格式无效。')
        seen = set()
        for row in data['models']:
            if not isinstance(row, dict) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_. -]{0,159}', row.get('id', '')):
                raise ValueError('模型 ID 无效。')
            if row['id'] in seen: raise ValueError('模型 ID 重复。')
            seen.add(row['id'])
            if not row.get('filename') and not row.get('path'): raise ValueError('模型缺少文件路径。')
            row.setdefault('context_limit', 32768)
            row.setdefault('default_context', min(32768, int(row['context_limit'])))
            row.setdefault('vision', False)
            row.setdefault('projector_filename', None)
            row.setdefault('status', 'unverified')
        temporary = self.path.with_suffix('.json.tmp')
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        os.replace(temporary, self.path)
        self.reload()

    def reload(self):
        with self._lock:
            data = json.loads(self.path.read_text(encoding='utf-8-sig'))
            if data.get('schema_version') != SCHEMA_VERSION or not isinstance(data.get('models'), list):
                raise ValueError('模型目录版本不受支持。')
            models = {}
            for source in data['models']:
                row = dict(source)
                row['label'] = row.get('display_name') or row['id']
                row['size'] = int(row.get('size_bytes') or 0)
                row['default_context'] = int(row.get('default_context') or 32768)
                row['context_limit'] = max(8192, min(MAX_CONTEXT, int(row.get('context_limit') or 32768)))
                models[row['id']] = row
            if not models: raise ValueError('模型目录为空，至少需要一个可回退模型。')
            self._models = models
            self._mtime = self.path.stat().st_mtime_ns

    def _fresh(self):
        try: changed = self.path.stat().st_mtime_ns != self._mtime
        except OSError: changed = True
        if changed: self.reload()

    def __getitem__(self, key):
        self._fresh(); return self._models[key]
    def __iter__(self):
        self._fresh(); return iter(tuple(self._models))
    def __len__(self):
        self._fresh(); return len(self._models)
    def get(self, key, default=None):
        self._fresh(); return self._models.get(key, default)

    def scan(self):
        self._fresh()
        known = set(self._models)
        found = []
        for path in self.directory.glob('*.gguf'):
            if path.name.lower().startswith('mmproj-') or path.name.endswith('.partial'):
                continue
            key = path.stem
            if key not in known:
                found.append({'id': key, 'path': str(path), 'size_bytes': path.stat().st_size,
                              'status': 'local_unregistered'})
        return found

    def register_local(self, path, display_name=None, projector_path=None):
        path = Path(path).expanduser().resolve(strict=True)
        if path.suffix.lower() != '.gguf' or path.stat().st_size < 1024 * 1024:
            raise ValueError('请选择完整的 GGUF 权重文件。')
        from gguf_info import read_metadata
        metadata = read_metadata(path)
        architecture = metadata.get('general.architecture')
        if not architecture: raise ValueError('GGUF 缺少 general.architecture。')
        context = int(metadata.get(architecture + '.context_length') or 32768)
        projector = str(Path(projector_path).resolve(strict=True)) if projector_path else None
        record = {'id': path.stem, 'display_name': display_name or path.stem, 'provider': 'local',
                  'repo_id': None, 'revision': None, 'filename': path.name, 'path': str(path),
                  'size_bytes': path.stat().st_size, 'sha256': None, 'architecture': architecture,
                  'quantization': metadata.get('general.file_type'), 'context_limit': min(MAX_CONTEXT, max(8192, context)),
                  'default_context': min(32768, context),
                  'chat_template': metadata.get('tokenizer.chat_template'), 'supports_tools': bool(metadata.get('tokenizer.chat_template')),
                  'vision': bool(projector), 'projector_filename': projector, 'runtime': 'llama-server',
                  'status': 'local_unverified', 'metadata_checked_utc': datetime.now(timezone.utc).isoformat()}
        data = json.loads(self.path.read_text(encoding='utf-8-sig'))
        data['models'] = [row for row in data['models'] if row.get('id') != record['id']] + [record]
        self.write(data)
        return record

    def validate_local(self, model_id, expected_sha256=None, hash_file=False):
        row = dict(self[model_id])
        path = Path(row['path']).resolve() if row.get('path') else self.directory / row['filename']
        if not path.is_file(): raise FileNotFoundError(str(path))
        actual_size = path.stat().st_size
        if row.get('size_bytes') and actual_size != int(row['size_bytes']):
            raise ValueError(f'模型大小与目录记录不符：期望 {row["size_bytes"]}，当前 {actual_size}')
        digest = None
        wanted = expected_sha256 or row.get('sha256')
        if hash_file or wanted:
            sha = hashlib.sha256()
            with path.open('rb') as handle:
                for block in iter(lambda: handle.read(8 * 1024 * 1024), b''): sha.update(block)
            digest = sha.hexdigest()
            if wanted and digest.lower() != wanted.lower(): raise ValueError('SHA256 与可信目录记录不符。')
        return {'id': model_id, 'path': str(path), 'size_bytes': actual_size,
                'sha256': digest, 'expected_sha256': wanted, 'hash_verified': bool(wanted and digest),
                'architecture': row.get('architecture'), 'runtime_test_required': True,
                'status': 'files_validated_runtime_pending'}
