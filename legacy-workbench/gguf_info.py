"""Read GGUF metadata without allocating or loading model tensor weights."""
import json
from pathlib import Path
import struct
import sys

FORMATS = {0:'B',1:'b',2:'H',3:'h',4:'I',5:'i',6:'f',7:'?',10:'Q',11:'q',12:'d'}

def read_metadata(path):
    with Path(path).open('rb') as file:
        def unpack(fmt):
            return struct.unpack('<'+fmt, file.read(struct.calcsize('<'+fmt)))[0]
        def string(keep=True):
            size = unpack('Q')
            if keep:
                return file.read(size).decode('utf-8',errors='replace')
            file.seek(size,1)
        def value(kind,keep=True):
            if kind == 8:
                return string(keep)
            if kind == 9:
                subtype, count = unpack('I'), unpack('Q')
                if not keep and subtype in FORMATS:
                    file.seek(struct.calcsize('<'+FORMATS[subtype])*count,1)
                    return
                values = []
                for _ in range(count):
                    item = value(subtype,keep)
                    if keep: values.append(item)
                return values if keep else None
            if kind not in FORMATS:
                raise ValueError('Unsupported GGUF metadata type '+str(kind))
            return unpack(FORMATS[kind])
        assert file.read(4)==b'GGUF'
        version, tensor_count, count = unpack('I'),unpack('Q'),unpack('Q')
        result = {'version':version,'tensor_count':tensor_count}
        for _ in range(count):
            key, kind = string(), unpack('I')
            keep = not key.startswith('tokenizer.') or key == 'tokenizer.chat_template'
            item = value(kind,keep)
            if keep: result[key] = item
        return result

if __name__ == '__main__':
    for name in sys.argv[1:]:
        metadata=read_metadata(name)
        metadata.pop('tokenizer.chat_template',None)
        print(Path(name).name,json.dumps(metadata,ensure_ascii=False,indent=2))
