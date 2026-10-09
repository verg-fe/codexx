"""Replay gateway-only context at its original history boundary.

Store hashes of client history and the injected notes, never the client prompt.
Changed/compacted history invalidates incompatible boundaries automatically.
"""
import hashlib
import json
import threading
import uuid
from pathlib import Path

LOCK = threading.RLock()
ROOT = Path(r'G:\LocalCodex\request-continuity')

def fingerprints(items):
    digest = hashlib.sha256()
    result = [digest.hexdigest()]
    for item in items:
        raw = json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
        digest.update(len(raw).to_bytes(8, 'big'))
        digest.update(raw)
        result.append(digest.hexdigest())
    return result

def reconcile(body, original_count, thread_id, root=ROOT):
    if not isinstance(body.get('input'), list):
        return {'runtime_context_replayed': 0}
    original = body['input'][:original_count]
    fresh = body['input'][original_count:]
    hashes = fingerprints(original)
    if not thread_id:
        # Some native Responses calls carry no thread identifier. Prefix checks
        # still prevent replay into a different history; isolate by stable
        # instructions, model and the first client item, not the changing tail.
        scope = [body.get('model'), body.get('instructions'), hashes[min(1, len(original))]]
        thread_id = 'anonymous:' + hashlib.sha256(json.dumps(scope, ensure_ascii=False).encode()).hexdigest()
    key = hashlib.sha256(str(thread_id).encode()).hexdigest()
    path = Path(root) / (key + '.json')
    with LOCK:
        records = []
        if path.is_file():
            try:
                records = json.loads(path.read_text(encoding='utf-8'))['boundaries']
            except (ValueError, KeyError, TypeError):
                records = []
        kept = []
        for record in records:
            count = record.get('count')
            if isinstance(count, int) and 0 <= count < original_count and record.get('fingerprint') == hashes[count]:
                kept.append(record)
        kept.sort(key=lambda record: record['count'])
        seen = {json.dumps(note, sort_keys=True, ensure_ascii=False)
                for record in kept for note in record['notes']}
        unique_fresh = []
        for note in fresh:
            signature = json.dumps(note, sort_keys=True, ensure_ascii=False)
            if signature not in seen:
                unique_fresh.append(note)
                seen.add(signature)
        fresh = unique_fresh
        injected = []
        offset = 0
        replayed = 0
        for record in kept:
            count = record['count']
            injected.extend(original[offset:count])
            injected.extend(record['notes'])
            replayed += len(record['notes'])
            offset = count
        injected.extend(original[offset:])
        injected.extend(fresh)
        if fresh:
            kept.append({'count': original_count, 'fingerprint': hashes[-1], 'notes': fresh})
        Path(root).mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix('.' + uuid.uuid4().hex + '.tmp')
        try:
            temporary.write_text(json.dumps({'boundaries': kept}, ensure_ascii=False), encoding='utf-8')
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
        body['input'] = injected
        return {'runtime_context_replayed': replayed, 'runtime_context_boundaries': len(kept)}
