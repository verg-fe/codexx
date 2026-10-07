"""Pinned, resumable HTTP range download. Verify bytes before activating a model."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import shutil
import threading
import time
import urllib.request
from core import MODEL_DIRECTORY

ROOT = Path(r'D:\LocalCodex')
REPO = 'https://huggingface.co/JackAgentLead/Jack-3.8-27B-V2-VL-16GB-VRAM/resolve/b5547a4b12824a1db2bf1af41504c3c7d600f8ac/'
FILES = [('Jack-3.8-27B-V2-VL-16GB-VRAM.gguf', 12120033600,
          'c20dab06e201b2591318526031982152a79dcda2169c4d3bbb3826b1a5597e95'),
         ('mmproj-Qwen3.8-27B-BF16.gguf', 931146528,
          '13cb7bebccbd04afc8f4090cb949ecf8937cdf7377c5799b1a0c594e7c0d3e16')]
progress_lock = threading.Lock()
done = threading.Event()

def digest(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()

def progress():
    while not done.wait(5):
        total = 0
        for name, size, _ in FILES:
            p = MODEL_DIRECTORY / name
            total += size if p.exists() else sum(x.stat().st_size for x in p.parent.glob(name + '.part[0-3]'))
        temp = ROOT / 'logs' / 'download-progress.tmp'
        temp.write_text(json.dumps({'bytes': total, 'total': 13051180128}))
        temp.replace(ROOT / 'logs' / 'download-progress.json')
        print(f'{total / 1e9:.2f} / 13.05 GB', flush=True)

def download(name, size, expected):
    target = MODEL_DIRECTORY / name
    if target.exists():
        if target.stat().st_size == size and digest(target) == expected:
            return
        raise RuntimeError(f'Existing model has incorrect hash: {name}')
    chunk = (size + 3) // 4
    partial = target.with_suffix('.gguf.partial')
    first = Path(str(target) + '.part0')
    if partial.exists() and not first.exists() and partial.stat().st_size <= chunk:
        partial.replace(first)

    def part(i):
        a, b = i * chunk, min((i + 1) * chunk, size) - 1
        path = Path(str(target) + f'.part{i}')
        for attempt in range(12):
            have = path.stat().st_size if path.exists() else 0
            if have == b - a + 1:
                return
            if have > b - a + 1:
                raise RuntimeError('Invalid range segment length')
            try:
                req = urllib.request.Request(REPO + name + '?download=true',
                    headers={'Range': f'bytes={a + have}-{b}', 'User-Agent': 'PersonalCodex/1.0'})
                with urllib.request.urlopen(req, timeout=90) as r:
                    expected_range = f'bytes {a + have}-{b}/{size}'
                    if r.status != 206 or r.headers.get('Content-Range') != expected_range:
                        raise RuntimeError('Server returned an unexpected byte range')
                    with path.open('ab') as f:
                        while block := r.read(1024 * 1024):
                            f.write(block)
                if path.stat().st_size == b - a + 1:
                    return
            except Exception as e:
                print(f'Segment {i}, retry {attempt + 1}: {e}', flush=True)
                time.sleep(min(2 ** attempt, 30))
        raise RuntimeError(f'Download retry limit: {name}, segment {i}')

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(part, range(4)))
    assembling = Path(str(target) + '.assembling')
    with assembling.open('wb') as out:
        for i in range(4):
            with Path(str(target) + f'.part{i}').open('rb') as source:
                shutil.copyfileobj(source, out, 8 * 1024 * 1024)
    if assembling.stat().st_size != size or digest(assembling) != expected:
        raise RuntimeError('SHA256 mismatch; model was not activated')
    assembling.replace(target)
    for i in range(4):
        Path(str(target) + f'.part{i}').unlink()
    print(f'Verified {name}', flush=True)

if __name__ == '__main__':
    threading.Thread(target=progress, daemon=True).start()
    try:
        for item in FILES:
            download(*item)
        (ROOT / 'logs' / 'download-complete.txt').write_text('Jack model and vision verified')
        (ROOT / 'logs' / 'download-progress.json').write_text(json.dumps({'bytes': 13051180128, 'total': 13051180128}))
    finally:
        done.set()
