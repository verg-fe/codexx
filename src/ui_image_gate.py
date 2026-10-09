"""Route tool-generated Android UI images to controls before CPU vision.

User attachments are untouched. Unknown controls remain explicitly unknown.
An explicit, hash-bound vision request allows a fresh screenshot through.
"""
import hashlib
import json
import time
from pathlib import Path

JOBS = Path(r'G:\LocalCodex\android-ui-jobs')


def _key(path):
    return hashlib.sha256(str(Path(path).resolve()).casefold().encode()).hexdigest()


def register_snapshot(path, state):
    JOBS.mkdir(parents=True, exist_ok=True)
    record = {'path': str(Path(path).resolve()), 'snapshot_id': state['snapshot_id'],
              'sha256': hashlib.sha256(Path(path).read_bytes()).hexdigest()}
    (JOBS / ('image-' + _key(path) + '.json')).write_text(json.dumps(record), encoding='utf-8')


def request_vision(path, reason):
    if not str(reason).strip():
        raise ValueError('Explain the unfamiliar/custom visual target first.')
    target = Path(path).resolve()
    roots = (JOBS.resolve(), Path(r'G:\LocalCodex\logs\android').resolve(),
             Path(r'D:\LocalCodex\logs\android').resolve())
    if not any(target.is_relative_to(root) for root in roots):
        raise ValueError('Use a phone screenshot saved under Android UI jobs/logs.')
    raw = target.read_bytes()
    if not raw.startswith(b'\x89PNG\r\n\x1a\n'):
        raise ValueError('A valid original PNG screenshot is required.')
    JOBS.mkdir(parents=True, exist_ok=True)
    record = {'sha256': hashlib.sha256(raw).hexdigest(), 'expires_at': time.time()+180,
              'reason': str(reason)[:500]}
    (JOBS / ('vision-' + _key(target) + '.json')).write_text(json.dumps(record), encoding='utf-8')
    return {'path': str(target), 'vision_allowed_for_seconds': 180, 'reason': record['reason'],
            'next': 'Open this exact path with view_image once; use normalized coordinates and guarded mapping/click tools.'}


def image_control_text(path):
    target = Path(path)
    if not target.is_file():
        return None
    try:
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        allowance = JOBS / ('vision-' + _key(path) + '.json')
        if allowance.is_file():
            record = json.loads(allowance.read_text(encoding='utf-8'))
            if record['sha256'] == digest and record['expires_at'] > time.time():
                return None
        index = JOBS / ('image-' + _key(path) + '.json')
        state = None
        if index.is_file():
            record = json.loads(index.read_text(encoding='utf-8'))
            if record['sha256'] == digest:
                state = json.loads((JOBS / (record['snapshot_id']+'.json')).read_text(encoding='utf-8'))
        roots = (JOBS.resolve(), Path(r'G:\LocalCodex\logs\android').resolve(),
                 Path(r'D:\LocalCodex\logs\android').resolve())
        if state is None and not any(target.resolve().is_relative_to(root) for root in roots):
            return None
        if state is None or time.time()-state['created_at'] > state['expires_after_seconds']:
            return '[Android control-first routing: this tool screenshot has no fresh matching control snapshot. Call android_ui_snapshot first to read visible text, descriptions and clickable candidates. Unknown/self-drawn content remains unknown. If the target cannot be found in controls or known templates, call android_ui_request_vision(image_path, reason), then reopen this original image. Do not guess taps.]'
        rows = state['candidates']
        brief = [{k:r.get(k) for k in ('id','text','description','resource_id','bounds','center','clickable')} for r in rows[:40]]
        return '[Android control-first routing; image pixels deferred. This is a control-tree observation, not a complete visual description. Unlabelled/custom areas remain unknown. Use android_ui_locate for additional targets, icon_find for known templates; for an unfamiliar target request android_ui_request_vision then reopen the image. Never guess taps.]\n' + json.dumps({'snapshot_id':state['snapshot_id'],'original_size':[state['width'],state['height']], 'candidates':brief,'truncated':len(rows)>40,'unlabelled_candidates':sum(not (r.get('text') or r.get('description')) for r in rows)}, ensure_ascii=False)
    except (OSError, ValueError, KeyError, TypeError):
        # A broken index never becomes a fabricated observation.
        return None


def defer_ui_tool_images(body):
    items = body.get('input')
    count = 0
    if not isinstance(items, list):
        return count
    calls = {x.get('call_id'):x for x in items if isinstance(x,dict) and x.get('type') in ('function_call','custom_tool_call')}
    observed = False
    for item in reversed(items):
        if not isinstance(item,dict):
            continue
        if item.get('type') in ('reasoning','function_call','custom_tool_call') or item.get('role') == 'assistant':
            observed = True
        if observed or item.get('type') != 'function_call_output':
            continue
        call = calls.get(item.get('call_id'),{})
        if 'view_image' not in str(call.get('name','')).lower():
            continue
        try:
            args = json.loads(call.get('arguments') or '{}')
            path = args.get('path') or args.get('image_path')
        except (ValueError,TypeError,AttributeError):
            continue
        if not path or not isinstance(item.get('output'),list):
            continue
        replacement = image_control_text(path)
        if replacement is None:
            continue
        for i,block in enumerate(item['output']):
            if isinstance(block,dict) and block.get('type') in ('input_image','image_url','image'):
                item['output'][i] = {'type':'input_text','text':replacement}
                count += 1
    return count
