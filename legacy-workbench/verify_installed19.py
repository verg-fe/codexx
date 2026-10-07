"""Short functional checks for the deployed v19, without changing user policy."""
import base64
import io
import json
import tomllib

from PIL import Image
import core
from verify_hip_runtime import health, response, text


def main():
    saved = core.load_settings()
    instructions = (core.ROOT / 'instructions.md').read_bytes()
    report = {'ok': False, 'short_requests_only': True, 'checks': {}}
    destination = core.ROOT / 'verification-installed19.json'

    def record(name, passed):
        report['checks'][name] = passed
        destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        assert passed, name
        print(name, flush=True)

    record('adapter_version', health()['adapter_version'] == core.ADAPTER_VERSION)
    limits = core.engine_limits(saved)
    report['work_context'], report['auto_compact'] = limits
    record('history_memory_32k_24k', saved['history_mode'] == 'memory' and limits == (32768, 24576))
    config = tomllib.loads((core.ROOT / 'codex-home' / 'config.toml').read_text(encoding='utf-8'))
    history = config['mcp_servers']['local_history']
    record('installed_history_server', history['command'] == str(core.ROOT / 'app' / 'MyCodex-history19' / 'MyCodex.exe')
           and '--history-server' in history['args'])
    record('native_context_and_auto_yes', config['model_context_window'] == 32768
           and config['model_auto_compact_token_limit'] == 24576 and config['approval_policy'] == 'never')
    live = core.active_model()
    report['active_model'] = live
    record('gpu_weights_and_gpu_kv', live['gpu_layers'] == 'all' and live['kv_cache_location'] == 'gpu'
           and not live['cpu_offload'])
    record('unlimited_reasoning_max_scheduling', live['reasoning_budget'] == -1 and live['performance_mode'] == 'max')
    record('allocated_context', core.api('/props')['default_generation_settings']['n_ctx'] == live['context'])
    result, elapsed = response({'instructions': '只输出计算结果。', 'input': '17乘19等于多少？'})
    report['text_seconds'] = elapsed
    record('text', '323' in text(result))
    result, elapsed = response({'instructions': '调用 ping 工具，message 为 v19-ready。', 'input': '验证工具调用。',
        'tools': [{'type': 'function', 'name': 'ping', 'parameters': {'type': 'object',
            'properties': {'message': {'type': 'string'}}, 'required': ['message'], 'additionalProperties': False}}],
        'tool_choice': {'type': 'function', 'name': 'ping'}})
    call = next(item for item in result['output'] if item.get('type') == 'function_call')
    report['function_seconds'] = elapsed
    record('function_call', call['name'] == 'ping' and json.loads(call['arguments'])['message'] == 'v19-ready')
    data = io.BytesIO()
    Image.new('RGB', (96, 96), (255, 0, 0)).save(data, format='WEBP', lossless=True)
    url = 'data:image/webp;base64,' + base64.b64encode(data.getvalue()).decode()
    result, elapsed = response({'instructions': '只用一个中文颜色词回答。', 'input': [{'role': 'user', 'content': [
        {'type': 'input_text', 'text': '图片的主要颜色是什么？'}, {'type': 'input_image', 'image_url': url}]}]})
    report['image_seconds'] = elapsed
    record('webp_image', '红' in text(result))
    record('user_policy_unchanged', saved == core.load_settings() and instructions == (core.ROOT / 'instructions.md').read_bytes())
    record('model_idle', all(not slot.get('is_processing') for slot in core.api('/slots')))
    report['ok'] = True
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print('Installed v19 functional verification complete.', flush=True)


if __name__ == '__main__':
    main()
