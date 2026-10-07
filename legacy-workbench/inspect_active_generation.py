"""Summarize the saved local model trace; never change the running request."""
from collections import Counter
import json
from pathlib import Path
import re

from core import ROOT


path = ROOT/'logs/generation/20261002T194333.396714Z-a9e2d7c16f82.jsonl'
parts, counts, transitions = {}, Counter(), []
metadata = {}
with path.open(encoding='utf-8') as source:
    for line in source:
        try:
            row = json.loads(line)
        except ValueError:
            continue  # A currently writing final line is not yet complete.
        if row.get('event') == 'request_started':
            metadata = row
        if row.get('event') in ('item_started', 'item_done', 'upstream_terminal', 'request_finished'):
            transitions.append(row)
        if row.get('event') == 'generated_delta':
            channel = row['channel']
            parts.setdefault(channel, []).append(row['delta'])
            counts[channel] += 1
reasoning = ''.join(parts.get('reasoning', []))
tools = ''.join(parts.get('tool_arguments', []))
outdir = ROOT/'diagnostics/pelican-20261003'
outdir.mkdir(parents=True, exist_ok=True)
(outdir/'reasoning.txt').write_text(reasoning, encoding='utf-8')
(outdir/'tool-arguments-partial.txt').write_text(tools, encoding='utf-8')
lines = Counter(re.sub(r'\s+', ' ', line).strip() for line in reasoning.splitlines() if len(line.strip()) > 45)
words = re.findall(r'[a-z]+', reasoning.lower())
phrases = Counter(' '.join(words[index:index+14]) for index in range(max(0, len(words)-13)))
record = {'trace': str(path), 'metadata': metadata, 'transitions': transitions,
          'delta_counts': dict(counts), 'characters': {key: sum(map(len, value)) for key, value in parts.items()},
          'repeated_lines': [{'count': count, 'text': text[:240]} for text, count in lines.most_common(8) if count > 1],
          'repeated_phrases': [{'count': count, 'text': text} for text, count in phrases.most_common(8)],
          'reasoning_head': reasoning[:2200], 'reasoning_tail': reasoning[-5000:],
          'tool_head': tools[:500], 'tool_tail': tools[-600:]}
(outdir/'report.json').write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(record, ensure_ascii=False, indent=2))
