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


def record_cpu_target_attempt(path, method):
    """Bind a completed CPU OCR/symbol pass to the screenshot it actually used."""
    target=Path(path).resolve()
    index=JOBS / ('image-' + _key(target) + '.json')
    if not index.is_file():return False
    try:
        record=json.loads(index.read_text(encoding='utf-8'))
        if record.get('sha256')!=hashlib.sha256(target.read_bytes()).hexdigest():return False
        state_path=JOBS/(str(record.get('snapshot_id',''))+'.json')
        state=json.loads(state_path.read_text(encoding='utf-8'))
        if time.time()-float(state['created_at'])>float(state.get('expires_after_seconds',180)):return False
        field='cpu_ocr_attempted' if method=='ocr' else 'cpu_symbol_attempted'
        state[field]=True
        state_path.write_text(json.dumps(state),encoding='utf-8')
        return True
    except (OSError,ValueError,KeyError,TypeError):
        return False


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
    index=JOBS / ('image-' + _key(target) + '.json')
    if not index.is_file():
        raise ValueError('Capture a fresh android_ui_snapshot and run CPU OCR or symbol/template matching on that exact snapshot before requesting vision.')
    try:
        registration=json.loads(index.read_text(encoding='utf-8'))
        if registration.get('sha256')!=hashlib.sha256(raw).hexdigest():
            raise ValueError('Screenshot changed; capture a fresh snapshot and repeat CPU target acquisition.')
        state=json.loads((JOBS/(registration['snapshot_id']+'.json')).read_text(encoding='utf-8'))
        if time.time()-float(state['created_at'])>float(state.get('expires_after_seconds',180)):
            raise ValueError('Snapshot expired; acquire a fresh screenshot and repeat CPU target acquisition.')
    except (OSError,KeyError,TypeError) as error:
        raise ValueError('Fresh snapshot metadata is unavailable; reacquire the screenshot before vision fallback.') from error
    if not (state.get('cpu_ocr_attempted') or state.get('cpu_symbol_attempted')):
        raise ValueError('General vision is gated until CPU OCR (for text) or CPU symbol/template matching (for glyphs) has run on this exact snapshot.')
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
        if state is None or time.time()-state['created_at'] > state.get('expires_after_seconds',180):
            return '[Android OCR-first routing; screenshot pixels withheld. Capture android_ui_snapshot, then run CPU android_ui_ocr for text or CPU symbol/template matching for glyphs. General vision is allowed only after those CPU paths fail on a fresh snapshot.]'
        return ('[Android OCR-first routing; screenshot pixels withheld. This is a fresh screenshot-only snapshot, '
                'not an accessibility-tree result. Run android_ui_ocr on this snapshot for text, or CPU '
                'symbol/template matching for a glyph. Only request general vision after a CPU attempt on '
                'this exact snapshot fails to identify the target. Do not guess coordinates.]\n' +
                json.dumps({'snapshot_id':state['snapshot_id'],'original_size':[state['width'],state['height']],
                    'cpu_ocr_attempted':bool(state.get('cpu_ocr_attempted')),
                    'cpu_symbol_attempted':bool(state.get('cpu_symbol_attempted'))},ensure_ascii=False))
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
