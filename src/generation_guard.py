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

DEFAULTS = dict(reasoning_tokens=1536, reasoning_seconds=60, generation_seconds=150,
                prefill_seconds=180, turn_seconds=600, repeated_failures=3, output_tokens=8192)

def guard_options(settings):
    stored = settings.get('generation_guard', {})
    ranges = dict(reasoning_tokens=(256,4096), reasoning_seconds=(15,120),
                  generation_seconds=(30,300), prefill_seconds=(30,600), turn_seconds=(120,1800),
                  repeated_failures=(2,5), output_tokens=(1024,16384))
    result = {}
    for name, default in DEFAULTS.items():
        try: value = int(stored.get(name, default))
        except (ValueError,TypeError,AttributeError): value = default
        low, high = ranges[name]
        result[name] = max(low,min(high,value))
    return result

def failure_signature(detail):
    text = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', detail)
    marker = re.search(r'(?:[\w.]+(?:Error|Exception):|FullyQualifiedErrorId\s*:|Traceback)', text)
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

class InferenceWatch:
    def __init__(self, root, thread, options, connection, downstream, model_pid=None):
        self.root=Path(root);self.thread=thread;self.options=options
        self.connection=connection;self.downstream=downstream;self.model_pid=model_pid
        self.done=threading.Event();self.stopped=threading.Event();self.lock=threading.Lock()
        self.sockets=[];self.reason=None;self.started=time.monotonic()
        self.generated=None;self.reasoning=None;self.response_id=None;self.text=''
        self.chunk_tail='';self.phrases=collections.Counter()
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
        if kind=='response.output_text.delta':
            self.text=(self.text+event.get('delta',''))[-2048:]
            if '<tool_call>' in self.text or re.search(r'<function=[^>]+>',self.text):
                self.stop('模型输出了未执行的工具标记，已停止本轮；请使用原生工具调用。')
        if self.stopped.is_set():raise GuardStopped(self.reason)

    def finish(self):
        self.done.set();self.connection.close()

    def failed_event(self):
        return {'type':'response.failed','response':{'id':self.response_id or 'resp_guard_'+uuid.uuid4().hex,
            'object':'response','created_at':int(time.time()),'status':'failed','output':[],
            'error':{'code':'generation_guard','message':self.reason or '本轮已停止。'}}}
