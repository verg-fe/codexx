"""Regress real frozen/windowed switches without a long-context benchmark."""
import ctypes
from ctypes import wintypes
import json
import queue
import time
import traceback
from pathlib import Path

import core


def main():
    from app import App
    report = {'ok': False, 'stages': [], 'approval_requests': 0,
              'adapter_version': core.ADAPTER_VERSION}
    output = core.ROOT / 'verification-window-switch.json'
    app = None
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.GetStdHandle.argtypes = [wintypes.DWORD]
    kernel.GetStdHandle.restype = wintypes.HANDLE

    def save():
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')

    def handles():
        return {'console_cp': kernel.GetConsoleCP(),
                'standard_handles': [kernel.GetStdHandle(v & 0xffffffff) for v in (-10, -11, -12)]}

    initial_handles = handles()
    report['initial_handles'] = initial_handles
    save()

    def stage(name):
        state = handles()
        assert state == initial_handles, (name, initial_handles, state)
        props = core.api('/props')
        current = core.active_model()
        context = app.settings['context']
        allocated = props['default_generation_settings']['n_ctx']
        assert context - 1 <= allocated < context + 256, (context, allocated)
        assert Path(props['model_path']) == core.model_file(core.MODEL)
        assert current['gpu_layers'] == 'all' and current['cpu_offload'] is False
        assert app.rpc.process.poll() is None
        assert core.load_settings()['context'] == context
        assert app.settings['model_contexts'][core.HUIHUI_MODEL] == 20480
        report['stages'].append({'stage': name, 'context': context,
                                'allocated_context': allocated, 'thread_id': app.thread_id,
                                'gpu_layers': current['gpu_layers'], 'handles': state})
        save()

    def collect(turn=False, expected_failure=False):
        deadline = time.monotonic() + 240
        answer = ''
        while time.monotonic() < deadline:
            try:
                event = app.events.get(timeout=0.25)
            except queue.Empty:
                app.update_idletasks()
                continue
            method = event.get('method', '')
            if 'id' in event and method:
                report['approval_requests'] += 1
                raise AssertionError('Unexpected approval request: ' + method)
            if method == 'item/agentMessage/delta':
                answer += event['params'].get('delta', '')
            if method == 'thread/tokenUsage/updated':
                report.setdefault('codex_contexts', []).append(
                    event['params']['tokenUsage'].get('modelContextWindow'))
            app.handle_event(event)
            if event.get('local') == 'error':
                raise RuntimeError(event['text'])
            if event.get('local') == 'settings_failed':
                if not expected_failure:
                    raise RuntimeError(event['text'])
                assert event.get('restored') is True, event
                assert 'WinError 6' not in event['text'], event
                report['rollback'] = {'restored': True, 'reason': event['text']}
                save()
                return event
            if event.get('local') == 'settings_applied' and not turn:
                assert not expected_failure, 'Capacity preflight unexpectedly accepted Huihui'
                return event
            if method == 'turn/completed' and turn:
                assert not event['params']['turn'].get('error'), event['params']['turn']
                return answer
        raise TimeoutError('Windowed context switch verification timed out')

    def turn(prompt):
        app.busy = True
        app.rpc.request('turn/start', {
            'threadId': app.thread_id, 'model': core.MODEL, 'effort': 'low',
            'collaborationMode': {'mode': 'default', 'settings': {
                'model': core.MODEL, 'reasoning_effort': 'low', 'developer_instructions': None}},
            'input': [{'type': 'text', 'text': prompt}]})
        answer = collect(turn=True)
        assert report['codex_contexts'][-1] == app.settings['context'], report
        return answer

    def apply(name, context, expected_failure=False):
        app.model_picker.set(core.MODELS[name]['label'])
        app.preview_model(app.model_picker.get())
        app.context_slider.set(context)
        app.preview_context(app.context_slider.get())
        assert app.pending_context == context
        app.apply_model_options()
        return collect(expected_failure=expected_failure)

    try:
        assert initial_handles['console_cp'] == 0, 'Test must run as a windowed executable'
        settings = core.load_settings()
        settings['model'] = core.MODEL
        settings['model_contexts'] = {core.MODEL: 20480, core.HUIHUI_MODEL: 20480}
        settings['cpu_offload'] = False
        core.prepare(settings)
        core.start_model(core.MODEL, 20480, wait=True)
        app = App(smoke=True)
        app.withdraw()
        app.project = core.ROOT / 'verification-project'
        app.project.mkdir(exist_ok=True)
        app.rpc = core.RpcClient(app.events.put)
        app.thread_id = app.rpc.request('thread/start', {
            'cwd': str(app.project), 'model': core.MODEL, 'modelProvider': 'qwen_local',
            'approvalPolicy': 'never', 'sandbox': 'danger-full-access',
            'config': {'model_context_window': 20480, 'model_auto_compact_token_limit': core.compact_for(20480)}})['thread']['id']
        thread_id = app.thread_id
        stage('20k_ready')
        token = 'WINDOW-SWITCH-100K-9070'
        first = turn('记住任务编号 ' + token + '。只复述编号，不运行工具。')
        assert token in first, first
        report['first_answer'] = first
        save()
        apply(core.MODEL, 65536)
        assert app.thread_id == thread_id
        stage('64k_applied')
        apply(core.MODEL, 102400)
        assert app.thread_id == thread_id
        stage('100k_applied')
        apply(core.HUIHUI_MODEL, 20480, expected_failure=True)
        assert core.selected_model(app.settings) == core.MODEL and app.settings['context'] == 102400
        assert app.thread_id == thread_id
        stage('100k_restored_after_capacity_rejection')
        final = turn('我们刚才约定的任务编号是什么？只复述编号，不运行工具。')
        assert token in final, final
        report['final_answer'] = final
        stage('100k_conversation_continued')
        report['ok'] = True
    except Exception as error:
        report['error'] = str(error)
        report['traceback'] = traceback.format_exc()
    finally:
        if app:
            if app.rpc:
                app.rpc.close()
                app.rpc.close()
            app.destroy()
        report['final_handles'] = handles()
        save()


if __name__ == '__main__':
    main()
