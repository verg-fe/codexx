"""Compare successive text template tokens; never persist prompt content.

This measures reusable text prefix, not actual cache hits. Multimodal estimates
cannot measure image embeddings. A new gateway starts with no previous sample.
"""
from array import array
import hashlib
import json
import threading

_lock = threading.Lock()
_previous = None
_MAX_TOKENS = 102400

def observe(tokens, body, image_count=0):
    global _previous
    current = array('q', tokens[:_MAX_TOKENS])
    def digest(value):
        return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    fields = {'instructions':digest(body.get('instructions','')),
              'tools':digest(body.get('tools',[]))}
    with _lock:
        before = _previous
        common = 0
        if before is not None:
            for a,b in zip(before[0],current):
                if a != b:break
                common += 1
        result = {'text_prefix_previous_available':before is not None,
                  'text_prefix_common_tokens':common if before is not None else None,
                  'text_prefix_previous_tokens':len(before[0]) if before is not None else None,
                  'text_prefix_image_count':image_count,
                  'text_prefix_comparison_capped':len(tokens)>_MAX_TOKENS,
                  'instructions_sha256':fields['instructions'],'tools_sha256':fields['tools'],
                  'text_prefix_changed_fields':[k for k in fields if before is not None and fields[k]!=before[1][k]]}
        _previous = (current,fields)
        return result
