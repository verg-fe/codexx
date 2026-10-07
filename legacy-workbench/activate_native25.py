"""Called only by the guarded installer while it owns the shared model mutex."""
import json
import core


def main():
    settings=core.load_settings()
    if settings.get('jack_xml_enabled',True):
        raise RuntimeError('XML 绕过设置未启用。')
    current=core.active_model()
    if core.selected_model(settings)!=core.MODEL or current.get('model')!=core.MODEL:
        raise RuntimeError('当前选择已经改变，未切换到其他模型。')
    # Preserve the actual allocation, backend, weights, cache and unlimited reasoning policy.
    core._start_model(core.MODEL,current['context'],True,current.get('context_limit'))
    live=core.active_model()
    template=core.chat_template_state(core.MODEL,settings)
    assert live['chat_template_policy']==template['policy'] and live['chat_template_sha256']==template['sha256']
    assert live['gpu_layers']=='all' and not live['cpu_offload'] and live['reasoning_budget']==-1
    assert live['context']==current['context'] and live['backend']==current['backend']
    report={'ok':True,'active':live,'weights_modified':False,'daily_thinking_limited':False}
    (core.ROOT/'activation-native25.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({'native_template_loaded':True,'model_pid':live['pid'],'backend':live['backend']}),flush=True)


if __name__=='__main__':main()
