"""Resumable 4-way parallel download of the Huihui Q4_K abliterated model with SHA256 verify.
Target: G:\LocalCodex\models\Huihui-Qwen3.8-27B-abliterated-Q4_K.gguf
"""
import hashlib
import json
import shutil
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from core import MODEL_DIRECTORY

ROOT = Path(r'D:\LocalCodex')
MODELS = MODEL_DIRECTORY
LOGS = ROOT / 'logs'
MODELS.mkdir(parents=True, exist_ok=True)
LOGS.mkdir(parents=True, exist_ok=True)

NAME = 'Huihui-Qwen3.8-27B-abliterated-Q4_K.gguf'
URL = ('https://hf-mirror.com/huihui-ai/Huihui-Qwen3.8-27B-abliterated-GGUF'
       '/resolve/main/' + NAME)
SIZE = 16810714400
SHA256 = '6c2c13cef89238c3604d756b07b3ef5fafebbd61095feb8553ff449c95e4c1c6'

target = MODELS / NAME
parts = [Path(str(target) + f'.part{i}') for i in range(4)]
chunk = (SIZE + 3) // 4


def digest(p):
    with p.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


if target.exists():
    if target.stat().st_size == SIZE and digest(target) == SHA256:
        print('Already complete and verified. Nothing to do.', flush=True)
        raise SystemExit(0)
    raise SystemExit('Existing file has wrong size/hash: ' + str(target))


def part(i):
    a, b = i * chunk, min((i + 1) * chunk, SIZE) - 1
    length = b - a + 1
    p = parts[i]
    for attempt in range(20):
        have = p.stat().st_size if p.exists() else 0
        if have == length:
            return
        if have > length:
            p.unlink()
            have = 0
        try:
            req = urllib.request.Request(
                URL, headers={'Range': f'bytes={have}-{b}',
                             'User-Agent': 'PersonalCodex/1.0'})
            with urllib.request.urlopen(req, timeout=120) as r:
                if r.status != 206:
                    raise RuntimeError(f'expected 206 got {r.status}')
                with p.open('ab') as f:
                    remaining = length - have
                    while remaining > 0:
                        block = r.read(min(2 * 1024 * 1024, remaining))
                        if not block:
                            break
                        f.write(block)
                        remaining -= len(block)
            if p.stat().st_size == length:
                return
        except Exception as e:
            print(f'seg{i} retry{attempt + 1}: {e}', flush=True)
            time.sleep(min(2 ** attempt, 30))
    raise SystemExit(f'seg{i} failed after retries; rerun to resume')


progress_stop = threading.Event()


def progress():
    while not progress_stop.wait(5):
        total = sum(p.stat().st_size for p in parts if p.exists())
        print(f'{total / 1e9:6.2f} / {SIZE / 1e9:.2f} GB', flush=True)
        (LOGS / 'download-progress.json').write_text(
            json.dumps({'bytes': total, 'total': SIZE}))


pt = threading.Thread(target=progress, daemon=True)
pt.start()
try:
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(part, range(4)))
finally:
    progress_stop.set()

asm = Path(str(target) + '.assembling')
with asm.open('wb') as out:
    for p in parts:
        with p.open('rb') as s:
            shutil.copyfileobj(s, out, 8 * 1024 * 1024)
if asm.stat().st_size != SIZE or digest(asm) != SHA256:
    raise SystemExit('SHA256 MISMATCH - model was NOT activated')
asm.replace(target)
for p in parts:
    p.unlink()
(LOGS / 'download-complete.txt').write_text('Huihui Q4_K verified')
print('DONE: verified ' + NAME, flush=True)
