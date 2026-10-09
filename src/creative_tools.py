"""Local Photoshop/CEP Premiere and CPU narration tools. No cloud credentials."""
import json
import os
from pathlib import Path
import re
import subprocess
import threading
import time
import urllib.request
import uuid
import wave

_voices_lock = threading.Lock()
_jobs = {}
_jobs_lock = threading.Lock()
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


def _powershell(root, payload, script, timeout=60, on_process=None):
    folder = Path(root) / 'creative-jobs' / uuid.uuid4().hex[:12]
    folder.mkdir(parents=True, exist_ok=True)
    request = folder / 'input.json'
    request.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
    command = folder / 'worker.ps1'
    command.write_text("param([string]$InputJson)\n$ErrorActionPreference='Stop'\n"
        "[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)\n"
        "$j=[IO.File]::ReadAllText($InputJson,[Text.Encoding]::UTF8)|ConvertFrom-Json\n" + script,
        encoding='utf-8-sig')
    process = subprocess.Popen(['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
        '-File', str(command), '-InputJson', str(request)], stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=NO_WINDOW)
    if on_process: on_process(process)
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.terminate(); process.communicate(timeout=10)
        raise TimeoutError('本地媒体工具超时；请检查软件界面和任务状态')
    if process.returncode:
        raise RuntimeError(stderr.decode('utf-8', errors='replace')[-1800:])
    return json.loads(stdout.decode('utf-8-sig').strip())






def voices(root):
    return _powershell(root, {}, "Add-Type -AssemblyName System.Speech\n"
        "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer\n"
        "try {@{backend='Windows CPU';voices=@($s.GetInstalledVoices()|ForEach-Object {"
        "@{name=$_.VoiceInfo.Name;language=$_.VoiceInfo.Culture.Name;enabled=$_.Enabled}})}|ConvertTo-Json -Depth 5}"
        " finally {$s.Dispose()}")


def _persist(root, job):
    folder = Path(root) / 'voice-jobs'
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / (job['id'] + '.json')
    with _jobs_lock:
        temp = target.with_suffix('.tmp')
        temp.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding='utf-8')
        os.replace(temp, target)


def voice_status(root, job_id):
    if not re.fullmatch(r'[0-9a-f]{12}', job_id or ''): raise ValueError('无效配音任务 ID')
    with _jobs_lock:
        if job_id in _jobs: return dict(_jobs[job_id])
    return json.loads((Path(root) / 'voice-jobs' / (job_id + '.json')).read_text(encoding='utf-8'))


def voice_cancel(root, job_id):
    job = voice_status(root, job_id)
    with _jobs_lock:
        live = _jobs.get(job_id)
        if not live and job['status'] not in ('completed', 'failed', 'cancelled'):
            raise ValueError('配音服务已退出；请重新提交任务')
        if live and live['status'] not in ('completed', 'failed', 'cancelled'):
            live['cancel_requested'] = True
            job = dict(live)
    _persist(root, job)
    return job


def _voice_worker(root, job, text, voice, rate, volume):
    process = None
    stopped = threading.Event()
    path = Path(root) / 'voice-jobs' / (job['id'] + '.wav')
    temporary = path.with_suffix('.partial.wav')
    def monitor():
        while not stopped.wait(.15):
            if job.get('cancel_requested') and process and process.poll() is None:
                process.terminate()
                return
    def register(p):
        nonlocal process
        process = p
        job['pid'] = p.pid
        threading.Thread(target=monitor, daemon=True).start()
    try:
        with _voices_lock:
            if job.get('cancel_requested'): raise InterruptedError('用户取消配音')
            job['status'] = 'synthesizing'; _persist(root, job)
            result = _powershell(root, {'text': text, 'voice': voice, 'rate': rate, 'volume': volume, 'output': str(temporary)},
                "Add-Type -AssemblyName System.Speech\n"
                "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer\n"
                "try {if($j.voice){$s.SelectVoice([string]$j.voice)} else {"
                "$v=$s.GetInstalledVoices()|Where-Object {$_.Enabled -and $_.VoiceInfo.Culture.Name -like 'zh-*'}|Select-Object -First 1;"
                "if($v){$s.SelectVoice($v.VoiceInfo.Name)}}\n"
                "$s.Rate=[int]$j.rate;$s.Volume=[int]$j.volume;$s.SetOutputToWaveFile([string]$j.output);"
                "$s.Speak([string]$j.text);$s.SetOutputToNull();"
                "@{voice=$s.Voice.Name;language=$s.Voice.Culture.Name}|ConvertTo-Json} finally {$s.Dispose()}",
                timeout=600, on_process=register)
            if job.get('cancel_requested'): raise InterruptedError('用户取消配音')
            with wave.open(str(temporary), 'rb') as audio:
                frames, hz = audio.getnframes(), audio.getframerate()
                if frames <= 0 or hz <= 0: raise RuntimeError('配音输出没有有效音频帧')
                stats = {'sample_rate': hz, 'channels': audio.getnchannels(), 'duration_seconds': frames / hz}
            os.replace(temporary, path)
            job.update(status='completed', path=str(path), bytes=path.stat().st_size, **result, **stats)
    except Exception as error:
        if job.get('cancel_requested'):
            job.update(status='cancelled', reason='用户取消配音')
        else:
            job.update(status='failed', error=f'{type(error).__name__}: {error}')
        temporary.unlink(missing_ok=True)
    finally:
        stopped.set()
        job['finished_at'] = time.time()
        _persist(root, job)


def narrate(root, text, voice='', rate=0, volume=100):
    if not text.strip() or len(text) > 20000: raise ValueError('配音文本必须为 1–20000 字符')
    if not -10 <= int(rate) <= 10 or not 0 <= int(volume) <= 100: raise ValueError('语速或音量超出有效范围')
    job = {'id': uuid.uuid4().hex[:12], 'status': 'queued', 'backend': 'Windows CPU', 'created_at': time.time()}
    with _jobs_lock: _jobs[job['id']] = job
    _persist(root, job)
    threading.Thread(target=_voice_worker, args=(root, job, text, voice, int(rate), int(volume)), daemon=True).start()
    return dict(job)


def schemas(service):
    empty = {'type': 'object', 'properties': {}}
    if service == 'voice':
        return [
            ('voice_list', '列出本机 CPU 配音声音和语言。', empty),
            ('voice_synthesize', '后台生成实际 WAV 配音，默认使用已安装中文声音，不占用显存。',
             {'type':'object','properties':{'text':{'type':'string'},'voice':{'type':'string'},'rate':{'type':'integer','default':0},'volume':{'type':'integer','default':100}},'required':['text']}),
            ('voice_job_status', '读取配音进度、WAV 路径、采样率与实际时长。',
             {'type':'object','properties':{'job_id':{'type':'string'}},'required':['job_id']}),
            ('voice_job_cancel', '取消排队/运行的配音，只停止该任务创建的 CPU 语音进程。',
             {'type':'object','properties':{'job_id':{'type':'string'}},'required':['job_id']}),
        ]
    return None


def dispatch(root, service, name, args):
    if service == 'voice':
        if name == 'voice_list': return voices(root)
        if name == 'voice_synthesize': return narrate(root, **args)
        if name == 'voice_job_status': return voice_status(root, args['job_id'])
        if name == 'voice_job_cancel': return voice_cancel(root, args['job_id'])
    raise ValueError('不支持的媒体工具')
