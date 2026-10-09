"""Persist generated Responses content without retaining it in RAM.

These files contain model output only. Request bodies, images and authorization
headers are never passed to this writer. Logging failures must not stop inference.
"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
import uuid
from task_artifacts import DraftStream


METADATA_FIELDS = ('thread_id', 'model', 'context_limit', 'runtime_context', 'kv_cache_location',
                   'prompt_tokens', 'reasoning_budget', 'media_converted_to_png', 'backend',
                   'retained_execution_failures', 'artifact_task_id')
METADATA_FIELDS += ('archived_tool_images', 'pending_tool_images', 'user_images', 'request_started_at')
DELTA_CHANNELS = {
    'response.reasoning_text.delta': 'reasoning',
    'response.reasoning_summary_text.delta': 'reasoning_summary',
    'response.output_text.delta': 'text',
    'response.function_call_arguments.delta': 'tool_arguments',
    'response.custom_tool_call_input.delta': 'tool_input',
}
DONE_CHANNELS = {
    'response.reasoning_text.done': ('reasoning', 'text'),
    'response.reasoning_summary_text.done': ('reasoning_summary', 'text'),
    'response.output_text.done': ('text', 'text'),
    'response.function_call_arguments.done': ('tool_arguments', 'arguments'),
    'response.custom_tool_call_input.done': ('tool_input', 'input'),
}
TERMINAL_EVENTS = ('response.completed', 'response.failed', 'response.incomplete')


def update_digest(digest, text):
    # Bounded temporary encodings even when a done event contains a long answer.
    for offset in range(0, len(text), 4096):
        digest.update(text[offset:offset+4096].encode('utf-8', errors='surrogatepass'))


class GenerationTrace:
    def __init__(self, directory, metadata):
        self.path = None
        self.file = None
        self.started = time.monotonic()
        self.last_flush = self.started
        self.streams = {}  # Only per-item character counts and fixed-size hashes.
        self.terminal = None
        self.adapter_outcome = None
        self.sequence = 0
        self.closed = False
        self.drafts = None
        self.pending_delta = None
        self.pending_since = self.started
        try:
            directory = Path(directory)
            directory.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
            self.path = directory / (stamp + '-' + uuid.uuid4().hex[:12] + '.jsonl')
            self.file = self.path.open('x', encoding='utf-8', errors='backslashreplace', buffering=8192)
            fields = {key: metadata[key] for key in METADATA_FIELDS if key in metadata}
            self._write({'event': 'request_started', 'format_version': 2,
                         'started_utc': datetime.now(timezone.utc).isoformat(), **fields}, flush=True)
            if metadata.get('draft_directory'):
                try:
                    self.drafts = DraftStream(metadata['draft_directory'], uuid.uuid4().hex[:12])
                except OSError:
                    print('draft autosave unavailable: local write failed', flush=True)
        except OSError:
            self._disable()

    def _disable(self):
        if self.file is not None:
            try:
                self.file.close()
            except OSError:
                pass
            self.file = None
        self.streams.clear()
        if self.drafts is not None:
            try:self.drafts.close()
            except OSError:pass
            self.drafts = None
        print('generation trace unavailable: local log write failed', flush=True)

    def _flush_delta(self):
        pending=self.pending_delta
        self.pending_delta=None
        if pending is not None:self._write(pending)

    def diagnostic(self, warning):
        self._write({'event':'diagnostic', **warning}, flush=True)

    def _write(self, record, flush=False):
        if record.get('event')!='generated_delta':self._flush_delta()
        if self.file is None or self.closed:
            return
        now = time.monotonic()
        self.sequence += 1
        record = {'seq': self.sequence, 'elapsed_seconds': round(now-self.started, 3), **record}
        try:
            self.file.write(json.dumps(record, ensure_ascii=False) + '\n')
            if flush or now-self.last_flush >= 1:
                self.file.flush()
                self.last_flush = now
        except OSError:
            self._disable()

    @staticmethod
    def _key(channel, data):
        index = data.get('summary_index', 0) if channel == 'reasoning_summary' else data.get('content_index', 0)
        return channel, str(data.get('item_id', '')), index

    def _text(self, key, text, source='delta'):
        if not isinstance(text, str) or not text or self.file is None:
            return
        count, digest = self.streams.get(key, (0, hashlib.sha256()))
        update_digest(digest, text)
        self.streams[key] = (count+len(text), digest)
        identity=(key, source)
        pending=self.pending_delta
        if pending and ((pending['channel'],pending['item_id'],pending['content_index']),pending['source'])!=identity:
            self._flush_delta();pending=None
        if pending is None:
            self.pending_since=time.monotonic()
            self.pending_delta={'event':'generated_delta','channel':key[0], 'item_id':key[1],
                'content_index':key[2], 'source':source, 'delta':text, 'delta_count':1}
        else:
            pending['delta']+=text
            pending['delta_count']+=1
        now=time.monotonic()
        if len(self.pending_delta['delta'])>=4096 or now-self.pending_since>=.25 or now-self.last_flush>=1:
            self._flush_delta()
        if self.drafts is not None and key[0] in ('reasoning', 'text'):
            try:self.drafts.feed(key, text)
            except OSError:
                try:self.drafts.close()
                except OSError:pass
                self.drafts = None
                print('draft autosave unavailable: local write failed', flush=True)

    def _complete_text(self, key, text):
        if not isinstance(text, str) or not text or self.file is None:
            return
        count, digest = self.streams.get(key, (0, hashlib.sha256()))
        prefix = hashlib.sha256()
        for offset in range(0, min(count, len(text)), 4096):
            update_digest(prefix, text[offset:min(offset+4096, count, len(text))])
        if len(text) >= count and prefix.digest() == digest.digest():
            # llama.cpp can emit a final parsed tail only in output_item.done.
            # Already-streamed text is not written a second time.
            self._text(key, text[count:], source='done_tail')
        else:
            # Preserve the authoritative final text if a backend revises a part.
            # Consumers replace earlier deltas for this item instead of appending.
            final_digest = hashlib.sha256()
            update_digest(final_digest, text)
            self.streams[key] = (len(text), final_digest)
            self._write({'event': 'stream_snapshot', 'channel': key[0], 'item_id': key[1],
                         'content_index': key[2], 'replaces_previous': True, 'text': text})
            if self.drafts is not None and key[0] in ('reasoning', 'text'):
                try:self.drafts.snapshot(key, text)
                except OSError:
                    try:self.drafts.close()
                    except OSError:pass
                    self.drafts=None

    def _item(self, item):
        if not isinstance(item, dict):
            return
        item_id = str(item.get('id', ''))
        kind = item.get('type')
        if kind in ('message', 'reasoning'):
            for index, block in enumerate(item.get('content') or []):
                channel = {'output_text': 'text', 'reasoning_text': 'reasoning'}.get(block.get('type'))
                if channel:
                    self._complete_text((channel, item_id, index), block.get('text'))
            for index, block in enumerate(item.get('summary') or []):
                self._complete_text(('reasoning_summary', item_id, index), block.get('text'))
        elif kind == 'function_call':
            self._complete_text(('tool_arguments', item_id, 0), item.get('arguments'))
        elif kind == 'custom_tool_call':
            self._complete_text(('tool_input', item_id, 0), item.get('input'))

    def event(self, data):
        if self.file is None or self.closed:
            return
        kind = data.get('type', '')
        if not kind and isinstance(data.get('error'), dict):
            # Installed llama.cpp can emit a bare error object in an SSE stream.
            error = data['error']
            self._write({'event': 'upstream_error', 'code': error.get('code'),
                         'error_type': error.get('type')}, flush=True)
        elif kind in DELTA_CHANNELS:
            self._text(self._key(DELTA_CHANNELS[kind], data), data.get('delta'))
        elif kind in DONE_CHANNELS:
            channel, field = DONE_CHANNELS[kind]
            self._complete_text(self._key(channel, data), data.get(field))
        elif kind == 'response.output_item.added':
            item = data.get('item') or {}
            self._write({'event': 'item_started', **{
                key: item[key] for key in ('id', 'type', 'name', 'call_id') if key in item}})
        elif kind == 'response.output_item.done':
            item = data.get('item') or {}
            self._item(item)
            self._write({'event': 'item_done', 'item_id': item.get('id'), 'item_type': item.get('type')})
        elif kind in TERMINAL_EVENTS:
            response = data.get('response') or {}
            for item in response.get('output') or []:
                self._item(item)
            self.terminal = kind
            # Select numeric/status metadata; never serialize the response body.
            usage = response.get('usage') or {}
            numeric_usage = {key: value for key, value in usage.items() if isinstance(value, (int, float))}
            for key, value in usage.items():
                if isinstance(value, dict):
                    numeric_usage[key] = {k: v for k, v in value.items() if isinstance(v, (int, float))}
            timings = {key: value for key, value in (data.get('timings') or {}).items()
                       if isinstance(value, (int, float))}
            self._write({'event': 'upstream_terminal', 'type': kind,
                         'response_id': response.get('id'), 'status': response.get('status'),
                         'usage': numeric_usage, 'timings': timings,
                         'error_code': (response.get('error') or {}).get('code'),
                         'incomplete_reason': (response.get('incomplete_details') or {}).get('reason')}, flush=True)
        elif kind == 'response.created':
            self._write({'event': 'response_created', 'response_id': (data.get('response') or {}).get('id')})
        elif kind == 'error':
            self._write({'event': 'upstream_error', 'code': data.get('code')}, flush=True)

    def adapter_terminal(self, data):
        self.adapter_outcome = data.get('type')
        self._write({'event': 'adapter_terminal', 'type': data.get('type'),
                     'error_code': ((data.get('response') or {}).get('error') or {}).get('code')}, flush=True)

    def finish(self, outcome, http_status=None):
        if self.closed:
            return
        counts = {}
        for (channel, _, _), (count, _) in self.streams.items():
            counts[channel] = counts.get(channel, 0) + count
        self._write({'event': 'request_finished', 'transport': outcome,
                     'upstream_terminal': self.terminal, 'adapter_terminal': self.adapter_outcome, 'http_status': http_status,
                     'generated_characters': counts}, flush=True)
        self.closed = True
        if self.file is not None:
            try:
                self.file.close()
            except OSError:
                print('generation trace unavailable: local log close failed', flush=True)
            self.file = None
        self.streams.clear()
        if self.drafts is not None:
            try:self.drafts.close()
            except OSError:pass
            self.drafts = None
