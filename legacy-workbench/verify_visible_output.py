"""Regress the observed blank turn, then run the same SVG task through the desktop."""
import json
from pathlib import Path
import queue
import time
import traceback
import xml.etree.ElementTree as ET

import core
import gateway


def main():
    from app import App
    report = {'ok': False, 'checks': {}, 'phase': 'starting', 'approval_requests': 0}
    output = core.ROOT / 'verification-visible-output.json'
    app = None
    saved_settings=core.prepare()
    saved_settings['kv_cache_location']='auto'

    def save(phase=None):
        if phase:
            report['phase'] = phase
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')

    try:
        temporary=json.loads(json.dumps(saved_settings))
        temporary['model']=core.MODEL
        temporary['model_contexts'][core.MODEL]=20480
        temporary['kv_cache_location']='auto'
        core.prepare(temporary)
        app = App(smoke=True)
        app.withdraw()
        app.handle_event({'method': 'turn/started', 'params': {'turn': {'id': 'blank-fixture'}}})
        app.handle_event({'method': 'thread/tokenUsage/updated', 'params': {'tokenUsage': {
            'last': {'inputTokens': 7174, 'outputTokens': 13306, 'totalTokens': 20480}}}})
        app.handle_event({'method': 'turn/completed', 'params': {'turn': {'id': 'blank-fixture'}}})
        assert '模型没有产生正文或工具结果' in app.chat.get('1.0', 'end')
        report['checks']['reasoning_only_turn_has_clear_warning'] = True
        app.handle_event({'method': 'turn/started', 'params': {'turn': {'id': 'final-only-fixture'}}})
        app.handle_event({'method': 'item/completed', 'params': {'item': {
            'type': 'agentMessage', 'id': 'final-only', 'text': 'FINAL_ONLY_VISIBLE_OK'}}})
        app.handle_event({'method': 'turn/completed', 'params': {'turn': {'id': 'final-only-fixture'}}})
        assert 'FINAL_ONLY_VISIBLE_OK' in app.chat.get('1.0', 'end')
        report['checks']['non_streamed_final_text_is_rendered'] = True
        empty = {'type': 'response.completed', 'response': {
            'status': 'completed', 'output': [{'type': 'reasoning', 'content': []}]}}
        adapted = gateway.adapt_event(empty, set(), set())[0]
        assert adapted['type'] == 'response.failed' and adapted['response']['error']['message']
        report['checks']['reasoning_only_sse_completion_is_failure'] = True
        for effort, budget in [('low', -1), ('medium', -1), ('xhigh', -1)]:
            normalized = gateway.normalize({'input': [], 'reasoning': {'effort': effort}})
            assert normalized['reasoning_budget_tokens'] == budget
            assert 'max_output_tokens' not in normalized
        report['checks']['effort_budgets'] = {'low': -1, 'medium': -1, 'xhigh': -1}
        assert core.kv_cache_location(109568,{'kv_cache_location':'auto'})=='gpu'
        assert core.kv_cache_location(110592,{'kv_cache_location':'auto'})=='ram'
        assert core.MAX_CONTEXT==256000
        gpu_args=core.model_args(core.MODEL,109568)
        ram_args=core.model_args(core.MODEL,256000)
        assert '--kv-offload' in gpu_args and '--no-kv-offload' not in gpu_args
        assert '--no-kv-offload' in ram_args and '--kv-offload' not in ram_args
        assert gpu_args[gpu_args.index('-ngl')+1]==ram_args[ram_args.index('-ngl')+1]=='all'
        app.context_slider.set(256000)
        app.preview_context(app.context_slider.get())
        assert app.pending_context==256000 and '实际输入' in app.cache_hint.cget('text')
        report['checks']['107k_gpu_108k_ram_250k_slider'] = True
        save('loading_bounded_model')
        core.start_model(wait=True)
        live = core.active_model()
        assert live['reasoning_budget'] == core.REASONING_BUDGET
        assert live['gpu_layers'] == 'all' and live['context'] == 20480
        report['active_model'] = live
        app.project = core.ROOT / 'verification-project/pelican-output-check'
        app.project.mkdir(exist_ok=True, parents=True)
        app.rpc = core.RpcClient(app.events.put)
        app.new_chat()
        app.effort.set('均衡思考')
        prompt = '画一只鹈鹕骑自行车的2d svg 的循环动画 要求鹈鹕踩着踏板前进 车轮旋转 翅膀摆动 背景移动'
        prompt += '\n请直接在当前目录创建 pelican-cycling.svg，使用纯 SVG/CSS 循环动画，控制在160行以内。完成后给出文件路径，不要只描述计划。'
        app.input.insert('1.0', prompt)
        started = time.monotonic()
        app.send_prompt()
        assert '模型正在处理，请稍候' in app.chat.get('1.0', 'end')
        report['checks']['visible_waiting_message'] = True
        deadline = started + 300
        save('native_svg_turn')
        while time.monotonic() < deadline:
            try:
                event = app.events.get(timeout=0.25)
            except queue.Empty:
                app.update_idletasks()
                continue
            method = event.get('method', '')
            if 'id' in event and method:
                report['approval_requests'] += 1
            if method == 'item/agentMessage/delta' and 'first_visible_seconds' not in report:
                if App.clean_answer(event['params'].get('delta', '')).strip():
                    report['first_visible_seconds'] = round(time.monotonic() - started, 2)
            if method == 'item/started' and event['params'].get('item', {}).get('type') in ('fileChange', 'commandExecution'):
                report.setdefault('tool_events', []).append(event['params']['item'].get('type'))
                save('native_tools_running')
            if method == 'thread/tokenUsage/updated':
                report['token_usage'] = event['params'].get('tokenUsage')
            app.handle_event(event)
            if event.get('local') == 'error':
                raise RuntimeError(event['text'])
            if method == 'turn/completed':
                assert not event['params']['turn'].get('error'), event['params']['turn']
                assert app.turn_visible_output, 'No visible native response or tool result'
                break
        else:
            app.interrupt()
            raise TimeoutError('The SVG turn did not finish within five minutes')
        report['seconds'] = round(time.monotonic() - started, 2)
        report['thread_id'] = app.thread_id
        report['answer'] = app.chat.get('1.0', 'end')[-6000:]
        svg = app.project / 'pelican-cycling.svg'
        assert svg.exists(), 'No SVG file was created by the actual coding engine'
        tree = ET.parse(svg)
        assert tree.getroot().tag == '{http://www.w3.org/2000/svg}svg'
        content = svg.read_text(encoding='utf-8')
        assert 'infinite' in content or 'repeatCount="indefinite"' in content
        assert '@keyframes' in content or 'animateTransform' in content
        assert report.get('tool_events'), 'No actual native tool execution'
        assert report['token_usage']['modelContextWindow'] == 20480
        report['artifact'] = str(svg)
        report['checks']['real_svg_request_has_visible_output_and_file'] = True
        app.rpc.close()
        app.rpc=None
        save('checking_250k_ram_kv_short_response')
        from verify_ram_kv import verify
        report['ram_kv_250k']=verify()
        report['checks']['250k_ram_kv_gpu_weights_short_response'] = True
        report['ok'] = True
        save('complete')
    except Exception as error:
        report['error'] = str(error)
        report['traceback'] = traceback.format_exc()
        save('failed')
    finally:
        if app:
            if app.rpc:
                app.rpc.close()
            app.destroy()
        try:
            core.prepare(saved_settings)
            core.start_model(wait=True)
            report['restored_settings']={'context':core.load_settings()['context'],
                'kv_cache_location':core.active_model().get('kv_cache_location'),'gpu_layers':core.active_model().get('gpu_layers')}
        except Exception as error:
            report['ok']=False
            report['restore_error']=str(error)
        save()


if __name__ == '__main__':
    main()
