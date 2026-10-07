import hashlib, os, shutil, sys, threading, time, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from core import MODEL_DIRECTORY

BASE = str(MODEL_DIRECTORY)
LOGS = r"D:\LocalCodex\logs"
STEM = "Huihui-Qwen3.8-27B-abliterated-Q4_K"
TARGET = os.path.join(BASE, STEM + ".gguf")
ASSEMBLING = TARGET + ".assembling"
PARTS = os.path.join(BASE, ".parts_q4k_fresh")
URL = ("https://hf-mirror.com/huihui-ai/Huihui-Qwen3.8-27B-abliterated-GGUF"
       "/resolve/main/Huihui-Qwen3.8-27B-abliterated-Q4_K.gguf")
TOTAL = 16810714400
OFFICIAL = "6c2c13cef89238c3604d756b07b3ef5fafebbd61095feb8553ff449c95e4c1c6"
NPARTS = 4
PART_SIZE = TOTAL // NPARTS
SLICE = 2 * 1024 * 1024
CHUNK = 1024 * 1024
MAX_RETRY = 5
lock = threading.Lock()

def log(m):
    with lock:
        print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)

def bounds(i):
    a = i * PART_SIZE
    return a, min(a + PART_SIZE, TOTAL) - 1

def fetch_range(a, b, timeout=90):
    req = urllib.request.Request(URL, headers={"Range": f"bytes={a}-{b}"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        if r.status != 206:
            raise IOError(f"want 206 got {r.status}")
        return r.read()

def verify_slices(path, a, b):
    cands = [a, (a + b) // 2 - SLICE // 2, b - SLICE + 1]
    seen, ok = set(), True
    with open(path, "rb") as f:
        for off in cands:
            off = max(a, min(off, b - SLICE + 1))
            if off in seen:
                continue
            seen.add(off)
            f.seek(off - a)
            loc = f.read(SLICE)
            rem = fetch_range(off, off + SLICE - 1)
            if len(loc) != SLICE or len(rem) != SLICE or loc != rem:
                log(f"part slice MISMATCH @ {off} (loc={len(loc)} rem={len(rem)})")
                ok = False
            else:
                log(f"part slice OK @ {off}")
    return ok

def part_job(i):
    a, b = bounds(i)
    expect = b - a + 1
    path = os.path.join(PARTS, f"part{i}.gguf")
    for att in range(1, MAX_RETRY + 1):
        if os.path.exists(path):
            os.remove(path)
        log(f"part{i} att{att}: Range {a}-{b} ({expect} bytes) fresh")
        try:
            req = urllib.request.Request(URL, headers={"Range": f"bytes={a}-{b}"})
            with urllib.request.urlopen(req, timeout=120) as r:
                if r.status != 206:
                    raise IOError(f"want 206 got {r.status}")
                done, t0, last = 0, time.time(), 0.0
                with open(path, "wb") as f:
                    while True:
                        buf = r.read(CHUNK)
                        if not buf:
                            break
                        f.write(buf)
                        done += len(buf)
                        if time.time() - last > 20:
                            last = time.time()
                            log(f"part{i} {done/1e9:.2f}/{expect/1e9:.2f} GB")
            if done != expect:
                raise IOError(f"short {done}/{expect}")
            log(f"part{i} done {done} bytes in {time.time()-t0:.0f}s")
            if verify_slices(path, a, b):
                log(f"part{i} VERIFIED")
                return True
            log(f"part{i} slice FAILED, retrying")
        except Exception as e:
            log(f"part{i} att{att} error: {e!r}")
        time.sleep(3)
    log(f"part{i} GAVE UP")
    return False

def main():
    for old in [ASSEMBLING] + [os.path.join(BASE, f"{STEM}.gguf.part{i}") for i in range(NPARTS)]:
        if os.path.exists(old):
            os.remove(old)
            log(f"removed stale {os.path.basename(old)}")
    if os.path.isdir(PARTS):
        shutil.rmtree(PARTS)
    os.makedirs(PARTS, exist_ok=True)
    log("starting fresh 4-way download from hf-mirror.com")
    with ThreadPoolExecutor(max_workers=NPARTS) as ex:
        futs = {ex.submit(part_job, i): i for i in range(NPARTS)}
        res = {futs[f]: f.result() for f in as_completed(futs)}
    if not all(res.values()):
        print("FAIL: part verification failed", flush=True)
        sys.exit(1)
    log("assembling")
    h, done = hashlib.sha256(), 0
    with open(ASSEMBLING, "wb") as out:
        for i in range(NPARTS):
            with open(os.path.join(PARTS, f"part{i}.gguf"), "rb") as f:
                while True:
                    buf = f.read(8 * 1024 * 1024)
                    if not buf:
                        break
                    out.write(buf)
                    h.update(buf)
                    done += len(buf)
    if done != TOTAL:
        print(f"FAIL assembled {done} != {TOTAL}", flush=True)
        sys.exit(1)
    dg = h.hexdigest()
    log(f"sha256={dg}")
    if dg != OFFICIAL:
        print("FAIL SHA256 MISMATCH", flush=True)
        sys.exit(1)
    os.replace(ASSEMBLING, TARGET)
    shutil.rmtree(PARTS)
    os.makedirs(LOGS, exist_ok=True)
    with open(os.path.join(LOGS, "download-complete.txt"), "w", encoding="utf-8") as f:
        f.write(f"Huihui Q4_K verified\nsha256={dg}\n")
    print(f"DONE: verified {TARGET}", flush=True)

if __name__ == "__main__":
    main()
