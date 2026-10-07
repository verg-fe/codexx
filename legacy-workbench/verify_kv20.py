"""Compare cache precision only after the observed native conversation ends.

The user's GUI, saved settings, weights, sampling and reasoning policy remain
unchanged. Exclusive model ownership queues new requests during the short test.
"""
import base64
import io
import json
from pathlib import Path
import socket
import statistics
import subprocess
import time
import urllib.error
import urllib.request

from PIL import Image
import core

THREAD = '01a0fef3-e61d-73b3-b562-c301d38376ac'
TURN = '01a0fef3-e679-7290-9368-e51e35b63491'
REPORT = core.ROOT / 'verification-kv20.json'
PORT = 8082


def native_state(path):
    latest = None
    terminal = False
    ended = set()
    with path.open(encoding='utf-8') as file:
        for line in file:
            try:
                event = json.loads(line)
            except ValueError:
                continue
            item = event.get('payload', {})
            if event.get('type') != 'event_msg':
                continue
            if item.get('type') == 'task_started':
                latest, terminal = item.get('turn_id'), False
            elif item.get('type') in ('task_complete', 'turn_aborted'):
                ended.add(item.get('turn_id'))
                if item.get('turn_id') == latest:
                    terminal = True
    return latest, terminal, ended


def guard():
    paths = list((core.ROOT / 'codex-home/sessions').rglob('*.jsonl'))
    observed = [path for path in paths if THREAD in path.name]
    if len(observed) != 1:
        return {'safe': False, 'reason': 'Observed conversation archive unavailable'}
    latest, terminal, ended = native_state(observed[0])
    if TURN not in ended or (latest and not terminal):
        return {'safe': False, 'reason': 'Observed native turn still active or changed'}
    for path in sorted(paths, key=lambda p: p.stat().st_mtime, reverse=True)[:6]:
        latest, terminal, _ = native_state(path)
        if latest and not terminal:
            return {'safe': False, 'reason': 'Another recent native turn remains active', 'file': path.name}
    cli_home=Path(r'C:\Users\18213\Desktop\codex-jack-cli\data\codex-home\sessions')
    if cli_home.exists():
        cli_paths=sorted(cli_home.rglob('*.jsonl'),key=lambda p:p.stat().st_mtime,reverse=True)[:6]
        for path in cli_paths:
            latest,terminal,_=native_state(path)
            if latest and not terminal:
                return {'safe':False,'reason':'A new CLI native turn remains active','file':path.name}
    try:
        if any(slot.get('is_processing') for slot in core.api('/slots')):
            return {'safe': False, 'reason': 'Inference active'}
    except (OSError, ValueError):
        return {'safe': False, 'reason': 'Cannot confirm inference idle'}
    return {'safe': True, 'reason': 'Native turns ended and inference idle'}


def request(route, body=None, timeout=180):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(f'http://127.0.0.1:{PORT}' + route, data=data,
        headers={'Authorization': 'Bearer ' + core.load_settings()['api_key'], 'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=timeout) as result:
        return json.load(result)


def memory(pid):
    # Separate dedicated and shared allocations: "-ngl all" alone does not prove
    # every allocation is physically resident in dedicated VRAM on Windows.
    command = ("Get-CimInstance Win32_PerfFormattedData_GPUPerformanceCounters_GPUProcessMemory "
               f"| Where-Object {{$_.Name -match '^pid_{int(pid)}_'}} "
               "| Select-Object DedicatedUsage,SharedUsage,TotalCommitted | ConvertTo-Json -Compress")
    try:
        result = subprocess.run(['powershell', '-NoProfile', '-Command', command], capture_output=True,
                                timeout=20, creationflags=core.NO_WINDOW)
        value = json.loads(result.stdout.decode('utf-8-sig').strip())
        rows = value if isinstance(value, list) else [value]
        return {field: sum(int(row[field]) for row in rows) for field in ('DedicatedUsage', 'SharedUsage', 'TotalCommitted')}
    except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired):
        return None


def start(cache, context, backend, output, vision=True):
    args = core.model_args(core.MODEL, context)
    for option, value in [('--port', str(PORT)), ('-ctk', cache), ('-ctv', cache),
                          ('--spec-type', 'none'), ('--slot-save-path', str(core.ROOT / 'cache/kv20-test'))]:
        args[args.index(option) + 1] = value
    if not vision:
        position = args.index('--mmproj')
        del args[position:position + 2]
        args.remove('--mmproj-offload')
    args += ['--verbosity', '1']
    log = output.open('w', encoding='utf-8')
    try:
        process = subprocess.Popen(args, cwd=core.runtime_directory(backend), env=core.runtime_environment(backend),
            stdin=subprocess.DEVNULL, stdout=log, stderr=log, creationflags=core.NO_WINDOW)
    finally:
        log.close()
    deadline = time.monotonic() + 120
    try:
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError('Private cache test server exited; inspect ' + str(output))
            try:
                if request('/health', timeout=2).get('status') == 'ok':
                    return process
            except (OSError, ValueError):
                pass
            time.sleep(.25)
        raise TimeoutError('Private cache test server did not become ready')
    except BaseException:
        stop(process)
        raise


def stop(process):
    if process and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def complete(messages, **extra):
    return request('/v1/chat/completions', {'model': core.MODEL, 'messages': messages,
        'max_tokens': 192, 'temperature': 0, 'chat_template_kwargs': {'enable_thinking': False}, **extra})


def functions_check(vision=True):
    result = complete([{'role': 'user', 'content': 'Return only the result of 17 * 19.'}])
    assert '323' in (result['choices'][0]['message'].get('content') or '')
    result = complete([{'role': 'user', 'content': 'Call ping with message kv-ready.'}],
        tools=[{'type': 'function', 'function': {'name': 'ping', 'parameters': {'type': 'object',
            'properties': {'message': {'type': 'string'}}, 'required': ['message'], 'additionalProperties': False}}}],
        tool_choice={'type': 'function', 'function': {'name': 'ping'}})
    call = result['choices'][0]['message']['tool_calls'][0]['function']
    assert call['name'] == 'ping' and json.loads(call['arguments'])['message'] == 'kv-ready'
    if vision:
        data = io.BytesIO()
        Image.new('RGB', (96, 96), (255, 0, 0)).save(data, format='PNG')
        url = 'data:image/png;base64,' + base64.b64encode(data.getvalue()).decode()
        result = complete([{'role': 'user', 'content': [{'type': 'text', 'text': 'What is the main color? One word.'},
            {'type': 'image_url', 'image_url': {'url': url}}]}])
        answer = result['choices'][0]['message'].get('content') or ''
        assert 'red' in answer.lower() or '红' in answer
    return {'text': True, 'function': True, 'image': True if vision else 'disabled_for_text_only_case'}


def main():
    report = {'ok': False, 'phase': 'waiting', 'guard': guard(), 'cases': {},
              'weights_changed': False, 'defaults_changed': False, 'max_filled_context': 0,
              'scope': 'same Jack weights and backend; Q4/Q8 KV and vision on/off; 32K allocated; short outputs; optional 70K allocation'}

    def save(phase):
        report['phase'] = phase
        REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({'phase': phase, 'safe': report['guard']['safe']}), flush=True)

    save('waiting')
    if not report['guard']['safe']:
        return
    with socket.socket() as test_socket:
        test_socket.bind(('127.0.0.1', PORT))  # Do not replace another service.
    saved = core.load_settings()
    if saved['model'] != core.MODEL or saved.get('cpu_offload'):
        raise RuntimeError('Comparison requires the all-GPU Jack setup')
    backend = report['backend'] = core.selected_backend(saved)
    original_settings = (core.ROOT / 'settings.json').read_bytes()
    original_instructions = (core.ROOT / 'instructions.md').read_bytes()
    process = None
    with core.model_lock():
        report['guard'] = guard()
        if not report['guard']['safe']:
            save('waiting')
            return
        try:
            core._stop_model()
            for cache, vision in (('q4_0', True), ('q8_0', True), ('q8_0', False)):
                if core.load_settings() != saved:
                    raise RuntimeError('User changed settings during the test; restore their selected runtime')
                label = cache + ('' if vision else '_text_only')
                case = report['cases'][label] = {'requests': [], 'cache_k': cache, 'cache_v': cache, 'vision': vision}
                save('loading_' + label)
                process = start(cache, 32768, backend, core.ROOT / 'logs' / ('kv20-' + label + '.log'), vision=vision)
                case['memory_after_load'] = memory(process.pid)
                assert request('/props')['default_generation_settings']['n_ctx'] == 32768
                for count in (90, 240):
                    reference = '\n'.join(f'def item_{i}(values):\n    return sorted(set(v for v in values if v >= {i}))\n' for i in range(count))
                    prompt = request('/apply-template', {'messages': [{'role': 'user', 'content':
                        'Read this Python reference and write varied unit tests.\n' + reference}],
                        'chat_template_kwargs': {'enable_thinking': False}})['prompt']
                    rows = []
                    for repeat in range(2):
                        save(f'checking_{label}_{count}_{repeat + 1}')
                        result = request('/completion', {'prompt': prompt, 'n_predict': 128, 'temperature': 0,
                            'seed': 42, 'ignore_eos': True, 'cache_prompt': False, 'stream': False})
                        timings = result['timings']
                        assert timings['predicted_n'] == 128 and result['content'].strip()
                        rows.append({'prompt_tokens': timings['prompt_n'], 'prefill_tokens_s': timings['prompt_per_second'],
                                     'output_tokens': timings['predicted_n'], 'output_tokens_s': timings['predicted_per_second']})
                        report['max_filled_context'] = max(report['max_filled_context'], timings['prompt_n'] + 128)
                    case['requests'].append({'reference_items': count, 'repetitions': rows,
                        'median_output_tokens_s': statistics.median(row['output_tokens_s'] for row in rows)})
                blocks = ['\n'.join(f'record_{i}: unrelated_example_{i}' for i in range(j, j + 250)) for j in (0, 250, 500)]
                recall = 'A=FALCON_7319\n' + blocks[0] + '\nB=ORANGE_8462\n' + blocks[1] + '\nC=RIVER_5207\n' + blocks[2]
                result = complete([{'role': 'user', 'content': recall + '\nReturn the values of A, B and C exactly.'}])
                answer = result['choices'][0]['message'].get('content') or ''
                case['recall'] = {value: value in answer for value in ('FALCON_7319', 'ORANGE_8462', 'RIVER_5207')}
                try:
                    case['functional'] = functions_check(vision=vision)
                except (OSError, ValueError, KeyError, AssertionError, IndexError) as error:
                    case['functional'] = {'ok': False, 'error': type(error).__name__ + ': ' + str(error)}
                case['memory_after_requests'] = memory(process.pid)
                case['ok'] = all(case['recall'].values()) and case['functional'].get('ok', True)
                stop(process)
                process = None
            for vision in (True, False):
                if core.load_settings() != saved:
                    raise RuntimeError('User changed settings during the test; restore their selected runtime')
                label = 'q8_70000' + ('' if vision else '_text_only')
                save('allocating_' + label + '_not_filling_70000')
                try:
                    process = start('q8_0', 70000, backend, core.ROOT / 'logs' / ('kv20-' + label + '.log'), vision=vision)
                    result = complete([{'role': 'user', 'content': 'Return only the result of 17 * 19.'}])
                    report[label + '_allocation'] = {'ok': '323' in (result['choices'][0]['message'].get('content') or ''),
                        'vision': vision, 'allocated_context': request('/props')['default_generation_settings']['n_ctx'],
                        'memory': memory(process.pid), 'is_long_context_performance_test': False}
                except (OSError, ValueError, KeyError, RuntimeError, TimeoutError) as error:
                    report[label + '_allocation'] = {'ok': False, 'error': type(error).__name__ + ': ' + str(error)}
                finally:
                    stop(process)
                    process = None
            report['ok'] = all(case.get('ok') for case in report['cases'].values())
        finally:
            stop(process)
            save('restoring_user_runtime')
            current = core.load_settings()
            name = core.selected_model(current)
            core._start_model(name, core.runtime_context_for(current, name, prompt_tokens=0), True, core.context_for(current, name))
            report['settings_unchanged'] = original_settings == (core.ROOT / 'settings.json').read_bytes()
            report['instructions_unchanged'] = original_instructions == (core.ROOT / 'instructions.md').read_bytes()
            report['restored_model'] = core.active_model()
            save('complete' if report['ok'] else 'failed_runtime_restored')


if __name__ == '__main__':
    main()
