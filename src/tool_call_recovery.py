"""Validate native calls and plan bounded retries; never execute partial arguments."""
import json

RECOVERABLE_CODES = frozenset({'tool_arguments_incomplete', 'tool_arguments_missing', 'tool_unknown'})
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


def recovery_prompt(state):
    return ('客户端诊断：上一条工具调用未执行。' + state.get('reason', '') + '\n'
            '继续当前任务，先检查已有文件，保留已经成功的修改。只做最小必要推理，'
            '每次写一个文件或一个小补丁，工具输入最多4000字符；大文件分段写入。'
            '完整结束 JSON 和补丁后再调用工具。不要原样重发上一条残缺调用。')
