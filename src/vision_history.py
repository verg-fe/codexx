"""Avoid re-encoding already observed UI screenshots on every tool step.

Only the inference copy is changed. User attachments and saved originals stay
available; newly returned tool images must reach the model at least once.
"""
import json

IMAGE_TYPES = {'input_image', 'image_url', 'image'}


def archive_observed_tool_images(body):
    stats = {'archived_tool_images': 0, 'pending_tool_images': 0, 'user_images': 0}
    items = body.get('input')
    if not isinstance(items, list):
        return stats
    calls = {item.get('call_id'): item for item in items
             if isinstance(item, dict) and item.get('type') in ('function_call', 'custom_tool_call')}
    observed = False
    for item in reversed(items):
        if not isinstance(item, dict):
            continue
        kind = item.get('type')
        if kind in ('reasoning', 'function_call', 'custom_tool_call') or item.get('role') == 'assistant':
            observed = True
        content = item.get('output') if kind == 'function_call_output' else item.get('content')
        if not isinstance(content, list):
            continue
        call = calls.get(item.get('call_id'), {})
        name = str(call.get('name') or '').lower()
        screenshot = ('view_image' in name or 'screenshot' in name)
        for index, block in enumerate(content):
            if not isinstance(block, dict) or block.get('type') not in IMAGE_TYPES:
                continue
            if kind != 'function_call_output':
                stats['user_images'] += 1
                continue
            if not (screenshot and observed):
                stats['pending_tool_images'] += 1
                continue
            try:
                arguments = json.loads(call.get('arguments') or '{}')
                path = arguments.get('path') or arguments.get('image_path') or ''
            except (ValueError, TypeError, AttributeError):
                path = ''
            content[index] = {'type': 'input_text', 'text':
                '[Previously observed tool screenshot. Its visual observation is in the following '
                'assistant messages; do not repeat the screenshot solely to inspect unchanged state. '
                'Use the current accessibility tree for controls; reopen the original image only '
                'when the task needs its pixels. Original: ' + (str(path) or str(item.get('call_id'))) + ']'}
            stats['archived_tool_images'] += 1
    return stats


def prefill_label(slot, routing, task_elapsed, now):
    processed = slot.get('n_prompt_tokens_processed')
    cached = slot.get('n_prompt_tokens_cache')
    images = routing.get('pending_tool_images', 0) + routing.get('user_images', 0)
    label = '正在处理输入'
    if isinstance(processed, int) and not isinstance(processed, bool) and processed >= 0:
        label += f' · 已处理 {processed:,} token'
    if isinstance(cached, int) and not isinstance(cached, bool) and cached >= 0:
        label += f' · KV复用 {cached:,} token'
        total = slot.get('n_prompt_tokens')
        if not isinstance(total, int) or isinstance(total, bool) or total <= 0:
            total = (processed if isinstance(processed, int) and not isinstance(processed, bool) else 0) + cached
        if total > 0:
            label += f' · 前缀命中约 {min(cached / total, 1.0):.1%}'
    else:
        label += ' · KV复用统计暂不可用'
    if images:
        label += f' · 视觉输入 {images} 张（图片处理时文字计数可能停留）'
    started = routing.get('request_started_at')
    if isinstance(started, (int, float)):
        label += f' · 本次请求 {max(0, int(now-started))} 秒'
    label += f' · 任务累计 {task_elapsed} 秒'
    return label
