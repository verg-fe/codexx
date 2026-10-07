"""Bounded live tail and readable export of locally saved generation events."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path


VIEW_CHARS = 40000
READ_BYTES = 131072
MAX_LINE_BYTES = 524288
LOCAL_ZONE = timezone(timedelta(hours=8))
CHANNEL_LABELS = {'reasoning': '思考', 'reasoning_summary': '思考摘要',
                  'text': '正文与状态', 'tool_arguments': '工具参数', 'tool_input': '工具输入'}
PHASE_LABELS = {'waiting': '等待模型', 'reasoning': '正在思考', 'message': '正在整理正文',
                'function_call': '正在生成工具调用', 'custom_tool_call': '正在生成工具调用'}


def trace_label(path):
    try:
        date = datetime.strptime(path.name.split('Z-')[0], '%Y%m%dT%H%M%S.%f').replace(tzinfo=timezone.utc)
        return date.astimezone(LOCAL_ZONE).strftime('%m-%d %H:%M:%S')+' · '+path.stem[-6:]
    except ValueError:
        return path.stem


def list_traces(directory, limit=30):
    directory = Path(directory)
    return sorted(directory.glob('*.jsonl'), key=lambda path: path.name, reverse=True)[:limit]


def render_record(row, previous_channel):
    event = row.get('event')
    if event in ('generated_delta', 'stream_snapshot'):
        channel = row.get('channel', 'text')
        header = '\n\n['+CHANNEL_LABELS.get(channel, channel)+']\n' if channel != previous_channel else ''
        if event == 'stream_snapshot':
            return header+'\n[以下为模型修正后的片段]\n'+row.get('text', ''), channel
        return header+row.get('delta', ''), channel
    if event == 'request_started':
        return ('[请求开始]\n模型：'+str(row.get('model', '本地模型'))+
                ' · 输入 '+str(row.get('prompt_tokens', '?'))+' token\n'), previous_channel
    if event == 'item_started' and row.get('type') in ('function_call', 'custom_tool_call'):
        return '\n\n[正在生成工具调用：'+str(row.get('name', '工具'))+']\n', previous_channel
    if event == 'request_finished':
        state = '连接已中断，已保留收到的内容' if row.get('transport') == 'client_disconnected' else (
            '模型请求已结束' if row.get('upstream_terminal') else '流已结束，未收到完成事件')
        return '\n\n['+state+']\n', previous_channel
    if event == 'upstream_error':
        return '\n[后端错误：'+str(row.get('code', '未知'))+']\n', previous_channel
    return '', previous_channel


class TraceTail:
    def __init__(self):
        self.file = None
        self.path = None
        self.partial = b''
        self.skipping = False
        self.channel = None
        self.phase = 'waiting'
        self.tool_name = None
        self.last_elapsed = 0
        self.finished = False
        self.characters = {}

    def select(self, path, tail=True):
        self.close()
        self.path = Path(path)
        self.file = self.path.open('rb')
        self.phase = 'waiting'
        self.tool_name = None
        self.last_elapsed = 0
        self.finished = False
        self.characters.clear()
        if tail:
            size = self.file.seek(0, 2)  # Handle size also works for open NTFS files.
            if size > READ_BYTES:
                self.file.seek(size-READ_BYTES)
                # Discard the first partial JSON line, with a bounded read.
                boundary = self.file.readline(MAX_LINE_BYTES)
                self.skipping = not boundary.endswith(b'\n')
            else:
                self.file.seek(0)

    def read(self):
        if self.file is None:
            return ''
        chunk = self.file.read(READ_BYTES)
        if not chunk:
            return ''
        if self.skipping:
            end = chunk.find(b'\n')
            if end < 0:
                return ''
            chunk = chunk[end+1:]
            self.skipping = False
        lines = (self.partial+chunk).split(b'\n')
        self.partial = lines.pop()
        rendered = []
        if len(self.partial) > MAX_LINE_BYTES:
            self.partial = b''
            self.skipping = True
            rendered.append('\n[较长日志片段已略过，导出完整日志可查看]\n')
        for line in lines:
            if len(line) > MAX_LINE_BYTES:
                rendered.append('\n[较长日志片段已略过，导出完整日志可查看]\n')
                continue
            try:
                row = json.loads(line)
            except (ValueError, UnicodeError):
                continue
            if not isinstance(row,dict):continue
            self.last_elapsed = row.get('elapsed_seconds', self.last_elapsed)
            if row.get('event') == 'item_started':
                self.phase = row.get('type', 'waiting')
                self.tool_name = row.get('name')
            elif row.get('event') in ('generated_delta', 'stream_snapshot'):
                channel = row.get('channel')
                if channel in ('reasoning', 'reasoning_summary'):
                    self.phase = 'reasoning'
                elif channel in ('tool_arguments', 'tool_input'):
                    self.phase = 'function_call'
                else:
                    self.phase = 'message'
                size = len(row.get('delta', row.get('text', '')))
                self.characters[channel] = size if row['event'] == 'stream_snapshot' else self.characters.get(channel, 0)+size
            elif row.get('event') == 'request_finished':
                self.finished = True
                self.characters = row.get('generated_characters', self.characters)
            text, self.channel = render_record(row, self.channel)
            if text:
                rendered.append(text)
        return ''.join(rendered)[-VIEW_CHARS:]

    def close(self):
        if self.file is not None:
            self.file.close()
        self.file = None
        self.partial = b''
        self.skipping = False
        self.channel = None


def export_trace(path, directory):
    path, directory = Path(path), Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory/(path.stem+'.txt')
    temporary = destination.with_suffix('.tmp')
    channel = None
    with path.open('rb') as source, temporary.open('w', encoding='utf-8') as target:
        target.write('本地模型生成记录 · '+trace_label(path)+'\n')
        # Export one event at a time, rather than loading the whole conversation.
        for line in source:
            try:
                row = json.loads(line)
            except (ValueError, UnicodeError):
                continue
            if not isinstance(row,dict):continue
            text, channel = render_record(row, channel)
            target.write(text)
    temporary.replace(destination)
    return destination
