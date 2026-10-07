"""Check the installed gateway's trace with one short, explicitly capped test.

This test cap belongs only to the verification request, never user settings.
"""
import json
import time
import urllib.request

import core


def main():
    report = {'ok': False, 'phase': 'starting', 'short_verification_only': True}
    destination = core.ROOT/'verification-generation-trace.json'
    def save(phase):
        report['phase'] = phase
        destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(phase, flush=True)
    save('waiting_for_installed_gateway_and_gpu_model')
    core.start_model(wait=True, prompt_tokens=0)
    settings = core.load_settings()
    headers = {'Authorization': 'Bearer '+settings['api_key'], 'Content-Type': 'application/json'}
    request = urllib.request.Request('http://127.0.0.1:8081/health', headers=headers)
    with urllib.request.urlopen(request, timeout=5) as response:
        health = json.load(response)
    assert health['adapter_version'] == core.ADAPTER_VERSION
    assert not any(slot.get('is_processing') for slot in core.api('/slots')), 'User model task is running'
    model = core.active_model()
    assert model['reasoning_budget'] == -1 and model['gpu_layers'] == 'all'
    directory = core.ROOT/'logs/generation'
    before = set(directory.glob('*.jsonl')) if directory.exists() else set()
    body = {'model': core.MODEL, 'instructions': '回答计算结果，只输出数字。',
            'input': [{'role': 'user', 'content': '17乘19等于多少？'}],
            'reasoning': {'effort': 'none'}, 'max_output_tokens': 32,
            'temperature': 0, 'stream': True}
    save('checking_one_32_token_stream')
    request = urllib.request.Request('http://127.0.0.1:8081/v1/responses',
        data=json.dumps(body, ensure_ascii=False).encode('utf-8'), headers=headers)
    events = []
    started = time.monotonic()
    with urllib.request.urlopen(request, timeout=120) as response:
        assert response.status == 200
        for line in response:
            if line.startswith(b'data:'):
                data = json.loads(line[5:].strip())
                events.append(data)
    report['stream_seconds'] = round(time.monotonic()-started, 3)
    deadline = time.monotonic()+3
    while True:
        created = set(directory.glob('*.jsonl'))-before
        if len(created) == 1:
            path = created.pop()
            rows = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]
            if rows and rows[-1]['event'] == 'request_finished':
                break
        if time.monotonic() >= deadline:
            raise AssertionError('Installed gateway did not finish a trace')
        time.sleep(.05)
    assert rows[0]['reasoning_budget'] == -1
    assert rows[0]['context_limit'] == 256000
    assert rows[0]['runtime_context'] == 109568 and rows[0]['kv_cache_location'] == 'gpu'
    assert rows[-1]['transport'] == 'upstream_eof'
    assert rows[-1]['upstream_terminal'] == 'response.completed'
    assert any(row['event'] == 'generated_delta' for row in rows)
    assert any(event.get('type') in ('response.completed', 'response.failed') for event in events)
    # Compare the final model text with the reconstructed persisted stream.
    reconstructed = {}
    for row in rows:
        if row['event'] in ('generated_delta', 'stream_snapshot'):
            key = row['channel'], row['item_id'], row['content_index']
            reconstructed[key] = row['text'] if row['event'] == 'stream_snapshot' else reconstructed.get(key, '')+row['delta']
    final = next(event['response'] for event in events if event.get('type') in ('response.completed', 'response.failed'))
    for item in final.get('output', []):
        for index, block in enumerate(item.get('content') or []):
            channel = {'reasoning_text': 'reasoning', 'output_text': 'text'}.get(block.get('type'))
            if channel and block.get('text'):
                assert reconstructed[(channel, item['id'], index)] == block['text']
    assert settings == core.load_settings(), 'Verification changed user settings'
    report.update(ok=True, trace=str(path), adapter_version=health['adapter_version'],
        live_model=model, saved_characters=rows[-1]['generated_characters'],
        checks={'installed_stream_matches_final_content': True,
                'finished_trace_flushed': True, 'user_limits_unchanged': True})
    save('complete')


if __name__ == '__main__':
    main()
