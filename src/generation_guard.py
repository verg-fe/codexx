"""Finite inference budgets, durable stop reasons and real socket cancellation."""
import collections
import hashlib
import json
from pathlib import Path
import re
import select
import socket
import threading
import time
import uuid

DEFAULTS = dict(reasoning_tokens=16384, reasoning_seconds=900, generation_seconds=1200,
                prefill_seconds=300, turn_seconds=3600, repeated_failures=3, output_tokens=32768,
                stall_seconds=90)

GUARD_PROFILES = {
    '日常：8K 思考 · 最多 8 分钟': dict(reasoning_tokens=8192,output_tokens=16384,reasoning_seconds=480,generation_seconds=720,turn_seconds=3600),
    '推荐：16K 思考 · 最多 15 分钟': dict(reasoning_tokens=16384,output_tokens=32768,reasoning_seconds=900,generation_seconds=1200,turn_seconds=3600),
    '复杂：32K 思考 · 最多 30 分钟': dict(reasoning_tokens=32768,output_tokens=49152,reasoning_seconds=1800,generation_seconds=2400,turn_seconds=7200),
}

def profile_label(settings):
    tokens=guard_options(settings)['reasoning_tokens']
    labels=list(GUARD_PROFILES)
    return labels[0] if tokens<=8192 else labels[1] if tokens<=16384 else labels[2]

def guard_options(settings):
    stored = settings.get('generation_guard', {})
    ranges = dict(reasoning_tokens=(1024,65536), reasoning_seconds=(60,3600),
                  generation_seconds=(120,4800), prefill_seconds=(30,900), turn_seconds=(600,14400),
                  repeated_failures=(2,5), output_tokens=(4096,98304),stall_seconds=(30,300))
    result = {}
    for name, default in DEFAULTS.items():
        try: value = int(stored.get(name, default))
        except (ValueError,TypeError,AttributeError): value = default
        low, high = ranges[name]
        result[name] = max(low,min(high,value))
    result['output_tokens']=max(result['output_tokens'],result['reasoning_tokens']+4096)
    result['generation_seconds']=max(result['generation_seconds'],result['reasoning_seconds']+120)
    return result

def failure_signature(detail):
    text = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', detail)
    errors=list(re.finditer(r'[\w.]+(?:Error|Exception):[^\r\n]*',text))
    if errors:return re.sub(r'\s+',' ',errors[-1].group().strip().lower())[:240]
    marker = re.search(r'(?:FullyQualifiedErrorId\s*:|Traceback)', text)
    text = text[marker.start():] if marker else text
    text = text.splitlines()[0].strip().lower()
    text = re.sub(r'0x[0-9a-f]+|\b\d+\b', '#', text)
    text = re.sub(r'[a-z]:[\\/][^\s]+', '<path>', text)
    return re.sub(r'\s+', ' ', text)[:240]

def repeated_failure(snapshot, limit):
    groups = collections.defaultdict(list)
    for failure in snapshot.get('failures', []):
        groups[failure_signature(failure['detail'])].append(failure)
    group = max(groups.values(), key=len, default=[])
    return group if len(group) >= limit else []

class GuardStore:
    def __init__(self, root):
        self.root = Path(root)
        self.directory = self.root / 'guards'
        self.directory.mkdir(parents=True,exist_ok=True)

    def path(self, thread):
        return self.directory / (hashlib.sha256(str(thread or 'standalone').encode()).hexdigest()+'.json')

    def read(self, thread):
        try:return json.loads(self.path(thread).read_text(encoding='utf-8'))
        except (OSError,ValueError):return {}

    def write(self, thread, reason, code='generation_guard'):
        value = dict(id=str(uuid.uuid4()), thread_id=thread, reason=reason, code=code,
                     blocked=True, timestamp=time.time())
        path=self.path(thread); temp=path.with_name(path.name+'.'+value['id']+'.tmp')
        temp.write_text(json.dumps(value,ensure_ascii=False),encoding='utf-8');temp.replace(path)
        return value

    def reset(self, thread):
        self.path(thread).unlink(missing_ok=True)

class GuardStopped(RuntimeError):pass

def unexecuted_tool_markup(text):
    """Recognize bare actionable markup, preserving quoted documentation."""
    text=re.sub(r'(?ms)^\s*(`{3,}|~{3,})[^\n]*\n.*?^\s*\1\s*$', '', text)
    text=re.sub(r'`[^`\n]*`','',text)
    text='\n'.join(line for line in text.splitlines() if not line.lstrip().startswith('>'))
    return bool(re.search(r'(?m)^\s*(?:<tool_call>\s*(?:\{|<function=[^>]+>)|<function=[^>]+>)',text))

class InferenceWatch:
    def __init__(self, root, thread, options, connection, downstream, model_pid=None, tool_enabled=False):
        self.root=Path(root);self.thread=thread;self.options=options
        self.connection=connection;self.downstream=downstream;self.model_pid=model_pid
        self.tool_enabled=tool_enabled
        self.done=threading.Event();self.stopped=threading.Event();self.lock=threading.Lock()
        self.sockets=[];self.reason=None;self.started=time.monotonic()
        self.generated=None;self.reasoning=None;self.response_id=None;self.text=''
        self.chunk_tail='';self.phrases=collections.Counter()
        self.last_progress=self.started
        self.worker=threading.Thread(target=self._run,daemon=True)

    def start(self):self.worker.start()

    def remember_socket(self, response):
        # HTTPConnection drops its socket reference after a Connection: close
        # response. Retain the actual stream socket so a blocked read can stop.
        try:self.sockets.append(response.fp.raw._sock)
        except AttributeError:pass

    def stop(self, reason, notify=True):
        with self.lock:
            if self.stopped.is_set():return
            self.reason=reason;self.stopped.set()
            if notify:GuardStore(self.root).write(self.thread,reason)
            sockets=self.sockets+[self.connection.sock]
            for stream in sockets:
                if stream is not None:
                    try:stream.shutdown(socket.SHUT_RDWR)
                    except OSError:pass
            threading.Thread(target=self._recover_backend,daemon=True).start()

    def _recover_backend(self):
        # Closing the upstream socket normally releases llama.cpp's slot. If
        # that fails, stop only the same owned PID and the same stuck task.
        from core import api, active_model, stop_model
        try:
            slots=api('/slots',timeout=1)
            tasks={s.get('id_task') for s in slots if s.get('is_processing')}
        except (OSError,ValueError):
            # Some optional engines do not expose slots. Serialize recovery
            # with inference so an old cancellation cannot kill a newer task.
            if self.done.wait(6):
                from gateway import INFERENCE_LOCK
                with INFERENCE_LOCK:
                    current=active_model()
                    if current.get('backend')=='moe4all' and current.get('pid')==self.model_pid:
                        stop_model()
            return
        if not tasks:return
        if self.done.wait(5):
            # Request cleanup does not prove the native generation has stopped.
            time.sleep(1)
        try:
            stuck=any(s.get('is_processing') and s.get('id_task') in tasks for s in api('/slots',timeout=1))
            if stuck and self.model_pid and active_model().get('pid')==self.model_pid:
                stop_model()
        except (OSError,ValueError,RuntimeError):pass

    def _run(self):
        while not self.done.wait(.25):
            now=time.monotonic()
            try:
                if select.select([self.downstream],[],[],0)[0] and not self.downstream.recv(1,socket.MSG_PEEK):
                    self.stop('客户端已断开，后台推理已取消。',notify=False);return
            except OSError:
                self.stop('客户端已断开，后台推理已取消。',notify=False);return
            if self.generated is None and now-self.started>self.options['prefill_seconds']:
                self.stop('输入处理超过时间限制，已停止本轮；请缩短上下文或降低窗口。');return
            if self.generated is not None and now-self.generated>self.options['generation_seconds']:
                self.stop('单次生成超过时间限制，已停止本轮并保留日志。');return
            if self.generated is not None and now-self.last_progress>self.options['stall_seconds']:
                self.stop('生成已连续 '+str(self.options['stall_seconds'])+' 秒没有新内容，已取消卡住的推理。');return
            if self.reasoning is not None and now-self.reasoning>self.options['reasoning_seconds']:
                self.stop('思考超过时间限制，已停止本轮；请根据实际报错继续最小验证。');return

    def event(self, event):
        kind=event.get('type','');now=time.monotonic()
        response=event.get('response') or {}
        if response.get('id'):self.response_id=response['id']
        if kind in ('response.incomplete','response.failed'):
            self.stop('模型未能完成本次输出，已停止本轮；请查看日志后缩短步骤继续。')
        if kind=='response.output_item.added' and (event.get('item') or {}).get('type')!='reasoning':
            self.reasoning=None
        if kind.endswith('.delta'):
            self.last_progress=now
            if self.generated is None:self.generated=now
            if 'reasoning' in kind:
                if self.reasoning is None:self.reasoning=now
                self.chunk_tail+=event.get('delta','')
                parts=re.split(r'\n\s*\n',self.chunk_tail)
                self.chunk_tail=parts[-1][-4096:]
                for part in parts[:-1]:
                    key=re.sub(r'\s+',' ',part).strip().lower()
                    if len(key)>120:
                        self.phrases[key]+=1
                        if self.phrases[key]>=3:self.stop('检测到相同思考段落反复输出，已停止循环。')
            else:self.reasoning=None
        if self.tool_enabled and kind=='response.output_item.done':
            item=event.get('item') or {}
            text='\n'.join(block.get('text','') for block in item.get('content',[]) if isinstance(block,dict))
            if item.get('type')=='message' and unexecuted_tool_markup(text):
                self.stop('模型输出了未执行的工具标记，已停止本轮；请使用原生工具调用。')
        if self.stopped.is_set():raise GuardStopped(self.reason)

    def finish(self):
        self.done.set();self.connection.close()

    def failed_event(self):
        return {'type':'response.failed','response':{'id':self.response_id or 'resp_guard_'+uuid.uuid4().hex,
            'object':'response','created_at':int(time.time()),'status':'failed','output':[],
            'error':{'code':'generation_guard','message':self.reason or '本轮已停止。'}}}
