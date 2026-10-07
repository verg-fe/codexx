"""Exercise native controls, real model reloads, conversation continuity and tools."""
import json
import queue
import time
import traceback
import core
from app import App

report = {'checks':{}, 'commands':[], 'approval_requests':0}

def save():
    (core.ROOT/'verification-model-picker.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')

def collect(app, timeout=1800, turn=False):
    deadline=time.monotonic()+timeout
    text=''
    while time.monotonic()<deadline:
        try:
            event=app.events.get(timeout=0.25)
        except queue.Empty:
            app.update_idletasks()
            continue
        kind=event.get('method')
        if 'id' in event and kind:
            report['approval_requests']+=1
            raise AssertionError('Unexpected approval or input request: '+kind)
        if kind=='item/agentMessage/delta':
            text+=event['params'].get('delta','')
        if kind=='thread/tokenUsage/updated':
            report.setdefault('windows_reported_by_codex',[]).append(event['params']['tokenUsage'].get('modelContextWindow'))
        if kind=='item/completed' and event['params'].get('item',{}).get('type')=='commandExecution':
            report['commands'].append(event['params']['item'])
        app.handle_event(event)
        if event.get('local')=='settings_failed':
            raise RuntimeError(event['text'])
        if event.get('local')=='settings_applied' and not turn:
            return text
        if kind=='turn/completed' and turn:
            assert not event['params']['turn'].get('error'), event['params']['turn'].get('error')
            return text
    raise TimeoutError('Native model picker operation timed out')

def turn(app, text):
    app.busy=True
    app.rpc.request('turn/start',{'threadId':app.thread_id,'effort':'low',
        'model':core.selected_model(app.settings),
        'collaborationMode':{'mode':'default','settings':{'model':core.selected_model(app.settings),
            'reasoning_effort':'low','developer_instructions':None}},
        'input':[{'type':'text','text':text}]})
    answer=collect(app,turn=True)
    props=core.api('/props')
    assert props['model_path']==str(core.model_file(core.selected_model(app.settings)))
    assert props['default_generation_settings']['n_ctx']==app.settings['context']
    report.setdefault('actual_backend_after_turns',[]).append({
        'model':core.selected_model(app.settings),'context':app.settings['context']})
    save()
    return answer

def apply(app, name, context):
    app.model_picker.set(core.MODELS[name]['label'])
    app.preview_model(app.model_picker.get())
    app.context_slider.set(context)
    app.preview_context(app.context_slider.get())
    assert app.pending_context==context
    app.apply_model_options()
    collect(app)
    props=core.api('/props')
    assert core.selected_model(app.settings)==name
    assert app.settings['context']==context
    assert props['default_generation_settings']['n_ctx']==context
    assert props['model_path']==str(core.model_file(name))
    assert json.loads((core.ROOT/'model-catalog.json').read_text(encoding='utf-8'))['models'][
        list(core.MODELS).index(name)]['context_window']==context
    report['checks'][name+'-'+str(context)]={'ok':True,'thread_id':app.thread_id,
        'context':context,'compact':app.settings['compact']}
    save()
    print('Applied',name,context,flush=True)

if __name__=='__main__':
    saved=core.prepare()
    app=None
    try:
        core.start_model(wait=True)
        app=App(smoke=True)
        app.withdraw()
        app.rpc=core.RpcClient(app.events.put)
        app.thread_id=app.rpc.request('thread/start',{'cwd':str(core.ROOT/'verification-project'),
            'approvalPolicy':'never','sandbox':'danger-full-access'})['thread']['id']
        token='PICKER-RETAIN-9070'
        first=turn(app,'记住任务编号 '+token+'。只复述编号，不运行工具。')
        assert token in first, first
        print('Initial real Codex conversation: OK',flush=True)
        apply(app,core.HUIHUI_MODEL,32768)
        second=turn(app,'先复述我们刚才的任务编号，再实际运行 python -c "print(\'PICKER_AUTO_YES_OK\')" 并报告输出。')
        assert token in second and 'PICKER_AUTO_YES_OK' in second, second
        assert any(c.get('exitCode')==0 and 'PICKER_AUTO_YES_OK' in c.get('aggregatedOutput','')
                   for c in report['commands']), 'No actual successful command'
        assert report['windows_reported_by_codex'][-1]==32768
        assert app.settings['model_contexts'][core.MODEL]==saved['model_contexts'][core.MODEL]
        apply(app,core.MODEL,65536)
        third=turn(app,'我们最初约定的任务编号是什么？只复述编号，不运行工具。')
        assert token in third, third
        assert report['windows_reported_by_codex'][-1]==65536
        assert app.settings['model_contexts'][core.HUIHUI_MODEL]==32768
        report['checks']['independent_choices_and_retained_history']={'ok':True,'answers':[first,second,third]}
        assert report['approval_requests']==0
        report['success']=True
        print('Real model picker / context reload / retained history / auto approval: OK',flush=True)
    except Exception as error:
        report['success']=False
        report['error']=str(error)
        report['traceback']=traceback.format_exc()
        raise
    finally:
        if app:
            if app.rpc: app.rpc.close()
            app.destroy()
        save()
        try:
            core.prepare(saved)
            core.stop_model()
        except Exception as error:
            report['restore_error']=str(error)
            report['success']=False
            raise
        finally:
            save()
