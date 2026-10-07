"""Compare local .assembling file against mirror source at key offsets (2 MB slices)."""
import urllib.request
from pathlib import Path

URL = ('https://hf-mirror.com/huihui-ai/Huihui-Qwen3.8-27B-abliterated-GGUF'
       '/resolve/main/Huihui-Qwen3.8-27B-abliterated-Q4_K.gguf')
SIZE = 16810714400
CHUNK = 4202678600
local = Path(r'D:\LocalCodex\models\Huihui-Qwen3.8-27B-abliterated-Q4_K.gguf.assembling')


def fetch(start, end):
    req = urllib.request.Request(
        URL, headers={'Range': f'bytes={start}-{end}', 'User-Agent': 'PersonalCodex/1.0'})
    with urllib.request.urlopen(req, timeout=60) as r:
        if r.status != 206:
            raise SystemExit(f'expected 206 got {r.status}')
        return r.read(end - start + 1)


SLICE = 2 * 1024 * 1024
tests = [
    ('file start', 0),
    ('part0 end / part1 start', CHUNK - 1024 * 1024),
    ('part1 end / part2 start', 2 * CHUNK - 1024 * 1024),
    ('part2 end / part3 start', 3 * CHUNK - 1024 * 1024),
    ('file end', SIZE - SLICE),
    ('mid part0', CHUNK // 2),
    ('mid part1', CHUNK + CHUNK // 2),
    ('mid part2', 2 * CHUNK + CHUNK // 2),
    ('mid part3', 3 * CHUNK + CHUNK // 2),
]

for name, off in tests:
    remote = fetch(off, off + SLICE - 1)
    with local.open('rb') as f:
        f.seek(off)
        ln = f.read(SLICE)
    status = 'OK' if ln == remote else 'MISMATCH'
    print(f'{name:30s} off={off:<12d} {status}', flush=True)
