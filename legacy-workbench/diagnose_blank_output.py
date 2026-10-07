"""Summarize the failed desktop conversation without dumping model reasoning."""
from collections import Counter
import json
from pathlib import Path
import core
from app import App

thread = '01a0fdc3-4772-7c63-8075-fa1976cd9d07'
path = next((core.ROOT / 'codex-home/sessions').rglob('*' + thread + '.jsonl'))
counts = Counter()
items = []
events = []
for line in path.read_text(encoding='utf-8').splitlines():
    row = json.loads(line)
    data = row.get('payload', {})
    kind = row.get('type', '') + '/' + data.get('type', '')
    counts[kind] += 1
    if row.get('type') == 'response_item':
        item = {'type': data.get('type'), 'role': data.get('role')}
        for field in ('content', 'summary'):
            blocks = data.get(field, [])
            texts = [block.get('text', '') for block in blocks if isinstance(block, dict)]
            if texts:
                text = '\n'.join(texts)
                item[field + '_characters'] = len(text)
                if data.get('role') == 'assistant':
                    item['visible_characters'] = len(App.clean_answer(text))
                if data.get('type') == 'reasoning':
                    item['longest_repeated_character_run'] = max(
                        (len(match.group(0)) for match in __import__('re').finditer(r'(.)\1{3,}', text)), default=0)
        if data.get('type') in ('function_call', 'custom_tool_call'):
            item['tool'] = data.get('name')
        items.append(item)
    elif row.get('type') == 'event_msg' and data.get('type') in ('token_count', 'task_complete', 'task_started'):
        events.append({key: value for key, value in data.items() if key not in ('last_agent_message',)})
report = {'thread_id': thread, 'counts': dict(counts), 'items': items, 'events': events}
(core.ROOT / 'diagnosis-blank-output.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(report, ensure_ascii=False))
