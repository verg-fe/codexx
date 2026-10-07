"""Copy only the three requested model files, verify every destination, keep sources."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import time

SOURCE=Path(r'D:\LocalCodex\models')
DESTINATION=Path(r'G:\LocalCodex\models')
REPORT=Path(r'D:\LocalCodex\model-migration.json')
FILES=[
    ('Jack-3.8-27B-V2-VL-16GB-VRAM.gguf',12120033600,'c20dab06e201b2591318526031982152a79dcda2169c4d3bbb3826b1a5597e95'),
    ('Huihui-Qwen3.8-27B-abliterated-Q4_K.gguf',16810714400,'6c2c13cef89238c3604d756b07b3ef5fafebbd61095feb8553ff449c95e4c1c6'),
    ('mmproj-Qwen3.8-27B-BF16.gguf',931146528,'13cb7bebccbd04afc8f4090cb949ecf8937cdf7377c5799b1a0c594e7c0d3e16'),
]
state={'ok':False,'phase':'copying','source':str(SOURCE),'destination':str(DESTINATION),
       'total_bytes':sum(size for _,size,_ in FILES),'copied_bytes':0,'files':[],'sources_removed':False}
began=time.monotonic()

def publish(**fields):
    state.update(fields)
    state['updated']=time.time()
    state['elapsed_seconds']=round(time.monotonic()-began,1)
    temporary=REPORT.with_suffix('.tmp')
    temporary.write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf-8')
    temporary.replace(REPORT)
    print(json.dumps({key:state[key] for key in ('phase','copied_bytes','total_bytes','elapsed_seconds')},ensure_ascii=True),flush=True)

def checked(path,root):
    resolved=path.resolve()
    assert root.resolve()==root, 'Model directory must not redirect to another location'
    assert resolved.parent==root and resolved.name==path.name, 'Unexpected model file destination'
    return resolved

def verify(path,name,size,expected):
    assert path.stat().st_size==size, 'Model size mismatch: '+name
    digest=hashlib.sha256()
    with path.open('rb') as source:
        while block:=source.read(16*1024*1024):
            digest.update(block)
    assert digest.hexdigest()==expected, 'Destination checksum mismatch: '+name

try:
    assert Path('G:/').exists(), 'G drive is unavailable'
    DESTINATION.mkdir(parents=True,exist_ok=True)
    missing=sum(size for name,size,_ in FILES if not (DESTINATION/name).exists())
    assert shutil.disk_usage(DESTINATION).free>=missing+1024*1024*1024, 'Not enough free space on G'
    publish()
    completed=0
    for name,size,expected in FILES:
        source=checked(SOURCE/name,SOURCE)
        destination=checked(DESTINATION/name,DESTINATION)
        assert source.stat().st_size==size, 'Unexpected source file size'
        if not destination.exists():
            partial=checked(destination.with_suffix('.gguf.moving'),DESTINATION)
            assert not partial.exists(), 'Partial copy already exists; left intact'
            digest=hashlib.sha256()
            count=0
            last=time.monotonic()
            publish(phase='copying',file=name)
            with source.open('rb') as input_file,partial.open('xb') as output_file:
                while block:=input_file.read(16*1024*1024):
                    output_file.write(block)
                    digest.update(block)
                    count+=len(block)
                    if time.monotonic()-last>=15:
                        publish(copied_bytes=completed+count)
                        last=time.monotonic()
                output_file.flush()
                os.fsync(output_file.fileno())
            assert count==size and digest.hexdigest()==expected, 'Source checksum mismatch'
            publish(phase='verifying_destination',copied_bytes=completed+count)
            verify(partial,name,size,expected)
            partial.rename(destination)
        else:
            publish(phase='verifying_existing_destination',file=name)
            verify(destination,name,size,expected)
        state['files'].append({'name':name,'size':size,'sha256':expected,'verified':True})
        completed+=size
        publish(copied_bytes=completed)
    publish(ok=True,phase='files_verified')
except Exception as error:
    publish(phase='failed',error=str(error))
    raise
