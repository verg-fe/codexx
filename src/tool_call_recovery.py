"""Validate native calls and plan bounded retries; never execute partial arguments."""
import json
import re

RECOVERABLE_CODES = frozenset({'tool_arguments_incomplete', 'tool_arguments_missing', 'tool_unknown'})

def context_overflow_detail(error):
    """Extract a short, structured context-window failure from nested RPC errors."""
    parts=[]
    stack=[error]
    seen=set()
    while stack:
        value=stack.pop()
        if isinstance(value,dict):
            if value.get('code')=='exceed_context_size_error':
                parts.append('exceed_context_size_error')
            for key in ('message','error','details'):
                if key in value:stack.append(value[key])
            continue
        if not isinstance(value,str):continue
        text=value.strip()
        if text in seen:continue
        seen.add(text);parts.append(text)
        if text.startswith('{') and len(text)<12000:
            try:stack.append(json.loads(text))
            except (ValueError,TypeError):pass
    text=' '.join(parts).lower()
    if not any(marker in text for marker in (
            'exceed_context_size_error','exceeds the available context size',
            'context length exceeded','maximum context length')):
        return None
    joined=' '.join(parts)
    requested=re.search(r'["\']?n_prompt_tokens["\']?\s*[:=]\s*["\']?(\d+)',joined,re.I)
    limit=re.search(r'["\']?n_ctx["\']?\s*[:=]\s*["\']?(\d+)',joined,re.I)
    if not requested:
        requested=re.search(r'request\s*\((\d+)\s*tokens?\)',joined,re.I)
    if not limit:
        limit=re.search(r'available context size\s*\((\d+)\s*tokens?\)',joined,re.I)
    return {'requested':int(requested.group(1)) if requested else None,
            'limit':int(limit.group(1)) if limit else None}

def context_overflow_summary(detail):
    if detail.get('requested') and detail.get('limit'):
        return f"上下文超限（{detail['requested']:,}/{detail['limit']:,} token）"
    return '上下文超出模型窗口'

def classify_unexecuted_tool_error(error):
    """Recognize only explicit malformed-call errors that guarantee no execution."""
    if isinstance(error, dict):
        code = error.get('code')
        message = error.get('message', '')
        if code in RECOVERABLE_CODES:
            return code, str(message or code)
        error = message
    text = str(error or '')
    lower = text.lower()
    not_executed = ('此调用未执行' in text or 'tool call was not executed' in lower or
                    'call was not executed' in lower)
    malformed_arguments = (
        '工具参数 json 未闭合或损坏' in lower or
        ('tool argument' in lower and any(word in lower for word in ('incomplete', 'malformed', 'invalid json')))
    )
    if not_executed and malformed_arguments:
        return 'tool_arguments_incomplete', text[:800]
    return None

class ToolCallFormatError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)

def decode_patch_arguments(raw):
    try:
        arguments = json.loads(raw)
    except (ValueError, TypeError) as error:
        raise ToolCallFormatError('tool_arguments_incomplete', '工具参数 JSON 未闭合或损坏；此调用未执行，请拆成小批次。') from error
    if not isinstance(arguments, dict) or not isinstance(arguments.get('input'), str):
        raise ToolCallFormatError('tool_arguments_missing', '补丁工具缺少字符串 input；此调用未执行，请按 schema 补齐。')
    return arguments['input']
BATCH_GUIDANCE = ('For file-writing tools, write one file or one small patch per call, at most 4000 '
                  'characters of source/patch input. Finish the JSON and patch terminator within the '
                  'current output budget. Do not put all source files into one call. Encode newlines '
                  'once in JSON; custom input must contain real newline characters after JSON decoding.')


def diagnose_call(item, advertised):
    name = item.get('name')
    if name not in advertised:
        return 'tool_unknown', '模型调用了未提供的工具；此调用未执行。请从实际工具列表选择。'
    raw = item.get('arguments', '')
    try:
        args = json.loads(raw)
    except (ValueError, TypeError):
        return 'tool_arguments_incomplete', ('工具参数 JSON 未闭合或损坏，可能耗尽本次总输出预算；'
                                            '此调用未执行。请将写入内容拆成小批次。')
    required = advertised[name].get('parameters', {}).get('required', [])
    if not isinstance(args, dict) or any(key not in args for key in required):
        return 'tool_arguments_missing', '工具参数缺少必填字段；此调用未执行。请按工具 schema 补齐。'
    return None


class RecoveryBudget:
    def __init__(self, limit=2):
        self.limit = limit
        self.counts = {}
        self.seen = set()
        self.ticket = 0
        self.enabled = True

    def success(self, thread):
        # Limit consecutive malformed-call retries, not unrelated later incidents.
        self.counts.pop(thread, None)

    def cancel(self, reset=False):
        self.ticket += 1
        self.enabled = bool(reset)
        if reset:
            self.counts.clear()
            self.seen.clear()

    def plan(self, thread, state):
        if not self.enabled or not thread or state.get('thread_id') != thread or state.get('code') not in RECOVERABLE_CODES:
            return None
        guard_id = state.get('id')
        if not guard_id or guard_id in self.seen or self.counts.get(thread, 0) >= self.limit:
            return None
        self.seen.add(guard_id)
        self.counts[thread] = self.counts.get(thread, 0) + 1
        return self.ticket, self.counts[thread]


def recovery_prompt(state, attempt=1):
    max_chars = 2000 if attempt <= 1 else 1000
    return ('客户端诊断：上一条工具调用未执行。' + state.get('reason', '') + '\n'
            '继续当前任务，先检查已有文件，保留已经成功的修改。只做最小必要推理，'
            f'每次写一个文件或一个小补丁，工具输入最多{max_chars}字符；大文件分段写入。'
            '完整结束 JSON 和补丁后再调用工具。不要原样重发上一条残缺调用。')
