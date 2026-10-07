"""Remove Jack's injected XML directive while preserving its chat/tool/vision protocol."""
import hashlib
import json
from pathlib import Path

from gguf_info import read_metadata
from directive_profiles import build_directive, selected_directive

START = '{%- set jack_prime_directive -%}'
END = '{%- endset %}'
INJECTION = "{%- set reasoning_instructions = jack_prime_directive + (('\\n\\n' + reasoning_instructions) if reasoning_instructions else '') %}"


def native_thinking_template(original):
    if not original.startswith(START) or original.count(INJECTION) != 1:
        raise ValueError('Jack 模板结构与已核对版本不同，未更改模板。')
    end = original.find(END, len(START))
    if end < 0:
        raise ValueError('Jack 模板缺少指令结束标记。')
    directive = original[len(START):end].strip()
    if '<Prime_Directive>' not in directive or '</Prime_Directive>' not in directive:
        raise ValueError('未确认 Jack XML 指令块，未更改模板。')
    result = original[end + len(END):].lstrip('\r\n')
    result = result.replace(INJECTION + '\n', '', 1) if INJECTION + '\n' in result else result.replace(INJECTION, '', 1)
    if 'jack_prime_directive' in result:
        raise ValueError('模板仍引用旧指令，未应用覆盖。')
    return result, directive


def ensure_native_template(root, model_file):
    # Read only GGUF metadata; never allocate, rewrite, or copy tensor weights.
    original = read_metadata(model_file).get('tokenizer.chat_template', '')
    result, _ = native_thinking_template(original)
    original_hash = hashlib.sha256(original.encode('utf-8')).hexdigest()
    payload = result.encode('utf-8')
    path = Path(root) / 'templates' / ('jack-native-' + original_hash[:12] + '.jinja')
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != payload:
            raise ValueError('外部模板被修改，与已核对版本不一致，未加载。')
    else:
        with path.open('xb') as stream:
            stream.write(payload)
    return {'policy': 'jack-native-v25', 'file': str(path),
            'sha256': hashlib.sha256(payload).hexdigest(), 'source_template_sha256': original_hash}


def profile_template(original, settings):
    """Replace only Jack's directive; retain every native tool/vision/reasoning branch."""
    native, _ = native_thinking_template(original)
    directive = build_directive(settings)
    if not directive:
        return original if selected_directive(settings) == 'legacy' else native
    original_tail = original[original.index(END, len(START)) + len(END):].lstrip('\r\n')
    literal = json.dumps(directive, ensure_ascii=False)
    return '{%- set jack_prime_directive = ' + literal + ' -%}\n' + original_tail


def ensure_profile_template(root, model_file, settings):
    mode = selected_directive(settings)
    if mode == 'native':
        return ensure_native_template(root, model_file)
    original = read_metadata(model_file).get('tokenizer.chat_template', '')
    result = profile_template(original, settings)
    payload = result.encode('utf-8')
    digest = hashlib.sha256(payload).hexdigest()
    path = Path(root) / 'templates' / ('jack-profile-' + mode + '-' + digest[:16] + '.jinja')
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != payload:
            raise ValueError('指令模板被修改，与当前选择不一致，未加载。')
    else:
        with path.open('xb') as stream:
            stream.write(payload)
    return {'policy': 'jack-profile-v26', 'mode': mode, 'file': str(path), 'sha256': digest,
            'source_template_sha256': hashlib.sha256(original.encode('utf-8')).hexdigest()}
