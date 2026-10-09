"""Tailnet-only phone upload portal and durable job inbox, stored on G:."""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import json
import os
from pathlib import Path
import secrets
import sys
import threading
import time
import urllib.parse
import uuid

PORT=8765
DATA_ROOT=Path(r'G:\LocalCodex\mobile-portal')
MAX_UPLOAD_BYTES=250*1024*1024
BLOCKED_SUFFIXES={'.exe','.dll','.msi','.scr','.com','.lnk'}
REASONING_EFFORTS={'low','medium','xhigh'}

def normalize_reasoning_effort(value=None):
    """Validate the per-task thinking level selected by desktop or phone."""
    if value is None:
        return 'medium'
    if not isinstance(value,str) or value not in REASONING_EFFORTS:
        raise ValueError('思考模式仅支持：快速、均衡、深入。')
    return value


class MobileInbox:
    def __init__(self,root=DATA_ROOT):
        self.root=Path(root)
        self.jobs=self.root/'jobs'
        self.jobs.mkdir(parents=True,exist_ok=True)
        self._lock=threading.RLock()
        self.token_path=self.root/'access-code.txt'
        if not self.token_path.exists():
            self.token_path.write_text(secrets.token_urlsafe(24),encoding='ascii')

    @property
    def access_code(self):
        return self.token_path.read_text(encoding='ascii').strip()

    def _path(self,job_id):
        if not isinstance(job_id,str) or len(job_id)!=32 or any(c not in '0123456789abcdef' for c in job_id):
            raise ValueError('无效任务编号。')
        return self.jobs/job_id/'job.json'

    def _read(self,job_id):
        path=self._path(job_id)
        data=json.loads(path.read_text(encoding='utf-8'))
        if data.get('id')!=job_id:raise ValueError('任务编号不匹配。')
        return data

    def _write(self,data):
        path=self._path(data['id']);path.parent.mkdir(parents=True,exist_ok=True)
        tmp=path.with_suffix('.tmp')
        tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
        os.replace(tmp,path)

    def create(self,task,reasoning_effort=None):
        task=str(task or '').strip()
        if not task or len(task)>10000:raise ValueError('请填写任务说明，最多 10000 个字符。')
        reasoning_effort=normalize_reasoning_effort(reasoning_effort)
        job_id=uuid.uuid4().hex
        row={'id':job_id,'task':task,'status':'uploading','created_at':time.time(),
             'files':[],'progress':'等待上传文件','cancel_requested':False,
             'reasoning_effort':reasoning_effort}
        with self._lock:self._write(row)
        (self.jobs/job_id/'uploads').mkdir(parents=True,exist_ok=True)
        return row

    def add_file(self,job_id,name,stream,length):
        # Validate the identifier before it is used in any filesystem path.
        self._path(job_id)
        if length<0 or length>MAX_UPLOAD_BYTES:raise ValueError('单个文件不能超过 250 MiB。')
        name=Path(str(name).replace('\\','/')).name.strip()
        if not name or name in ('.','..') or len(name)>180:raise ValueError('文件名无效。')
        if Path(name).suffix.lower() in BLOCKED_SUFFIXES:raise ValueError('此类可执行或系统文件不能上传。')
        path=self.jobs/job_id/'uploads'/name
        with self._lock:
            row=self._read(job_id)
            if row['status']!='uploading':raise ValueError('任务已提交，不能再添加文件。')
            if len(row['files'])>=20:raise ValueError('一个任务最多上传 20 个文件。')
            if sum(f.get('size',0) for f in row['files'])+length>1024*1024*1024:
                raise ValueError('一个任务的附件合计不能超过 1 GiB。')
            if any(f['name']==name for f in row['files']):raise ValueError('文件名重复，请先在手机上重命名。')
        temp=path.with_name(path.name+'.upload-'+uuid.uuid4().hex)
        written=0
        try:
            with temp.open('xb') as out:
                while written<length:
                    chunk=stream.read(min(1024*1024,length-written))
                    if not chunk:raise ValueError('上传中断，文件未收完整。')
                    out.write(chunk);written+=len(chunk)
                out.flush();os.fsync(out.fileno())
            with self._lock:
                row=self._read(job_id)
                if row['status']!='uploading':raise ValueError('任务已提交，不能再添加文件。')
                if any(f['name']==name for f in row['files']):raise ValueError('文件名重复，请先在手机上重命名。')
                os.replace(temp,path)
                row['files'].append({'name':name,'path':str(path),'size':written})
                row['progress']='文件已收妥';self._write(row)
        except Exception:
            try:temp.unlink(missing_ok=True)
            except OSError:pass
            raise
        return written

    def submit(self,job_id):
        with self._lock:
            row=self._read(job_id)
            if row['status']!='uploading':raise ValueError('任务已经提交或已处理。')
            if not row['files']:raise ValueError('请先上传至少一个文件。')
            row.update(status='queued',progress='已排队，等待本机 Huihui',submitted_at=time.time())
            self._write(row)
            return row

    def cancel(self,job_id):
        with self._lock:
            row=self._read(job_id)
            if row['status'] in ('uploading','queued','waiting_model','needs_review'):
                row.update(status='cancelled',progress='已取消',finished_at=time.time())
            elif row['status']=='processing':
                row['cancel_requested']=True;row['progress']='正在请求停止当前任务'
            self._write(row)
            return row

    def claim_next(self):
        with self._lock:
            candidates=[]
            for path in self.jobs.glob('*/job.json'):
                try:
                    row=json.loads(path.read_text(encoding='utf-8'))
                    if row.get('status')=='queued':candidates.append(row)
                except (OSError,ValueError):continue
            if not candidates:return None
            row=min(candidates,key=lambda x:x.get('submitted_at',x.get('created_at',0)))
            row.update(status='processing',progress='Huihui 正在处理',started_at=time.time())
            self._write(row)
            return row

    def update(self,job_id,**values):
        with self._lock:
            row=self._read(job_id);row.update(values);self._write(row);return row

    def get(self,job_id):
        with self._lock:return self._read(job_id)

    def list(self):
        rows=[]
        with self._lock:
            for path in self.jobs.glob('*/job.json'):
                try:rows.append(json.loads(path.read_text(encoding='utf-8')))
                except (OSError,ValueError):continue
        return sorted(rows,key=lambda x:x.get('created_at',0),reverse=True)[:50]

    def recover_interrupted(self):
        """Never duplicate a turn on restart; surface unfinished work for review."""
        with self._lock:
            for path in self.jobs.glob('*/job.json'):
                try:row=json.loads(path.read_text(encoding='utf-8'))
                except (OSError,ValueError):continue
                if row.get('status')=='processing':
                    row.update(status='needs_review',progress='桌面工作台曾重启；请检查会话后重新提交',finished_at=time.time())
                    self._write(row)


def _asset_root():
    if getattr(sys,'frozen',False):return Path(sys._MEIPASS)/'mobile-app'
    return Path(__file__).resolve().parent/'mobile-app'


class MobileUploadServer:
    def __init__(self,inbox:MobileInbox,port=PORT):
        self.inbox=inbox;self.port=port;self.server=None;self.thread=None

    def start(self):
        inbox=self.inbox
        class Handler(BaseHTTPRequestHandler):
            protocol_version='HTTP/1.1'
            def log_message(self,*args):return
            def normalized_path(self):
                path=urllib.parse.urlsplit(self.path).path
                for prefix in ('/mycodex','/huihui'):
                    if path==prefix:return '/'
                    if path.startswith(prefix+'/'):return path[len(prefix):]
                return path
            def reply(self,status,body,ctype='application/json; charset=utf-8'):
                data=body if isinstance(body,bytes) else json.dumps(body,ensure_ascii=False).encode('utf-8')
                self.send_response(status);self.send_header('Content-Type',ctype)
                self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','no-store')
                # Close on every response so a rejected upload body cannot be parsed as a new request.
                self.send_header('Connection','close');self.close_connection=True
                self.send_header('X-Content-Type-Options','nosniff')
                self.send_header('Referrer-Policy','no-referrer')
                self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'")
                self.end_headers();self.wfile.write(data)
            def authorized(self):
                supplied=self.headers.get('Authorization','')
                return supplied.startswith('Bearer ') and hmac.compare_digest(supplied[7:],inbox.access_code)
            def do_GET(self):
                path=self.normalized_path()
                assets={'/':'index.html','/index.html':'index.html','/manifest.webmanifest':'manifest.webmanifest',
                        '/sw.js':'sw.js','/icon.svg':'icon.svg'}
                if path in assets:
                    file=_asset_root()/assets[path]
                    if not file.is_file():return self.reply(404,{'error':'app asset missing'})
                    ctype='text/html; charset=utf-8' if file.suffix=='.html' else 'application/manifest+json' if file.suffix=='.webmanifest' else 'image/svg+xml' if file.suffix=='.svg' else 'text/javascript; charset=utf-8'
                    return self.reply(200,file.read_bytes(),ctype)
                if path=='/api/jobs':
                    if not self.authorized():return self.reply(401,{'error':'请填写桌面端显示的接入码。'})
                    rows=[]
                    for row in inbox.list():
                        rows.append({k:row.get(k) for k in ('id','task','status','progress','created_at','started_at','finished_at','reasoning_effort')}
                            | {'result':str(row.get('result',''))[:4000]}
                            | {'files':[f['name'] for f in row.get('files',[])]})
                    return self.reply(200,{'jobs':rows})
                if path.startswith('/api/jobs/'):
                    if not self.authorized():return self.reply(401,{'error':'请填写桌面端显示的接入码。'})
                    try:
                        job_id=path.split('/')[3];row=inbox.get(job_id)
                        safe={k:row.get(k) for k in ('id','task','status','progress','created_at','started_at','finished_at','reasoning_effort')}
                        safe['result']=str(row.get('result',''))[:4000]
                        safe['files']=[f['name'] for f in row.get('files',[])]
                        return self.reply(200,safe)
                    except (ValueError,OSError,IndexError):return self.reply(404,{'error':'找不到任务。'})
                return self.reply(404,{'error':'not found'})
            def do_POST(self):
                if not self.authorized():return self.reply(401,{'error':'接入码无效。'})
                path=self.normalized_path()
                try:length=int(self.headers.get('Content-Length','0'))
                except ValueError:return self.reply(400,{'error':'请求长度无效。'})
                if length<0:return self.reply(400,{'error':'请求长度无效。'})
                if length>20000:return self.reply(413,{'error':'请求太大。'})
                try:data=json.loads(self.rfile.read(length) or b'{}')
                except ValueError:return self.reply(400,{'error':'JSON 格式错误。'})
                try:
                    if path=='/api/jobs':
                        row=inbox.create(data.get('task',''),data.get('reasoning_effort'));return self.reply(201,{'id':row['id'],'status':row['status'],'reasoning_effort':row['reasoning_effort']})
                    parts=path.strip('/').split('/')
                    if len(parts)==4 and parts[0]=='api' and parts[1]=='jobs' and parts[3]=='submit':
                        row=inbox.submit(parts[2]);return self.reply(200,{'id':row['id'],'status':row['status']})
                    if len(parts)==4 and parts[0]=='api' and parts[1]=='jobs' and parts[3]=='cancel':
                        row=inbox.cancel(parts[2]);return self.reply(200,{'id':row['id'],'status':row['status']})
                except (ValueError,OSError) as error:return self.reply(400,{'error':str(error)})
                return self.reply(404,{'error':'not found'})
            def do_PUT(self):
                if not self.authorized():return self.reply(401,{'error':'接入码无效。'})
                path=self.normalized_path();parts=path.strip('/').split('/')
                if len(parts)!=5 or parts[:2]!=['api','jobs'] or parts[3]!='files':return self.reply(404,{'error':'not found'})
                try:
                    length=self.headers.get('Content-Length')
                    size=int(length) if length is not None else -1
                    if size<0:return self.reply(411,{'error':'上传请求缺少有效长度。'})
                    name=urllib.parse.unquote(parts[4])
                    written=inbox.add_file(parts[2],name,self.rfile,size)
                    return self.reply(201,{'bytes':written,'name':Path(name).name})
                except (ValueError,OSError) as error:return self.reply(400,{'error':str(error)})
        self.server=ThreadingHTTPServer(('127.0.0.1',self.port),Handler)
        self.server.daemon_threads=True
        self.port=self.server.server_address[1]
        self.thread=threading.Thread(target=self.server.serve_forever,name='mycodex-mobile-upload',daemon=True)
        self.thread.start()
        return self.port

    def close(self):
        if self.server:
            self.server.shutdown();self.server.server_close();self.server=None
        if self.thread and self.thread is not threading.current_thread():self.thread.join(timeout=3)
        self.thread=None
