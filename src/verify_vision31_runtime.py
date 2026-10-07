"""Short real image probes, including the desktop's native localImage path."""
import base64
import json
import os
from pathlib import Path
import queue
import time
import urllib.request
from unittest.mock import patch
from PIL import Image, ImageDraw, ImageFont
import core


def request(route, body):
    req=urllib.request.Request('http://127.0.0.1:8081'+route,
        data=json.dumps(body,ensure_ascii=False).encode('utf-8'),
        headers={'Authorization':'Bearer '+core.load_settings()['api_key'],'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=90) as response:return json.load(response)


def main():
    daily=core.ROOT;saved=(daily/'settings.json').read_bytes();settings=core.load_settings()
    root=daily/'verification-project/vision31';root.mkdir(exist_ok=True)
    report={'ok':False,'phase':'testing','scope':'Synthetic image recognition and one isolated native image task; no long-context stress test.'}
    path=daily/'verification-vision31-runtime.json'
    def save():path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    save()
    rpc=None;turn=None;thread=None;events=queue.Queue()
    try:
        assert core.server_ready()
        live=core.active_model()
        assert live.get('model')==core.HUIHUI_IQ3S_MODEL and live.get('vision_enabled') is True
        assert live.get('reasoning_budget')==-1 and live.get('context')==core.WORK_CONTEXT
        props=core.api('/props');assert props.get('modalities',{}).get('vision') is True
        report['runtime']={k:live.get(k) for k in ['model','context','backend','gpu_layers','kv_cache_location','reasoning_budget','vision_enabled','vision_projector']}
        font=ImageFont.truetype(r'C:\Windows\Fonts\arial.ttf',62)
        shapes=[('617','red','triangle'),('842','blue','circle')]
        files=[];outputs=[];checks={}
        base={'model':core.HUIHUI_IQ3S_MODEL,'temperature':0,'max_tokens':96,'stream':False,
            'chat_template_kwargs':{'enable_thinking':False}}
        for index,(number,color,shape) in enumerate(shapes):
            image=Image.new('RGB',(512,384),'white');draw=ImageDraw.Draw(image)
            draw.text((120,24),number,font=font,fill='black')
            if shape=='triangle':draw.polygon([(256,133),(134,330),(378,330)],fill=color)
            else:draw.ellipse((158,133,354,329),fill=color)
            file=root/f'card-{index}.png';image.save(file);files.append(file)
            url='data:image/png;base64,'+base64.b64encode(file.read_bytes()).decode('ascii')
            prompt='Read the printed number, main shape color and shape. Reply only NUMBER|COLOR|SHAPE in English. Do not guess from the filename.'
            if index==0:
                answer=request('/v1/chat/completions',{**base,'messages':[{'role':'user','content':[
                    {'type':'text','text':prompt},{'type':'image_url','image_url':{'url':url}}]}]})
                text=answer['choices'][0]['message'].get('content') or ''
            else:
                answer=request('/v1/responses',{**base,'input':[{'role':'user','content':[
                    {'type':'input_text','text':prompt},{'type':'input_image','image_url':url}]}]})
                text=''.join(b.get('text','') for item in answer.get('output',[]) for b in item.get('content',[]) if b.get('type')=='output_text')
            checks[f'image_{index}_number_color_shape']=all(word in text.lower() for word in (number,color,shape))
            outputs.append({'route':'chat' if index==0 else 'responses','answer':text,'timings':answer.get('timings')})
            (root/f'raw-image-{index}.json').write_text(json.dumps(answer,ensure_ascii=False,indent=2),encoding='utf-8')
        report.update(checks=checks,image_outputs=outputs,phase='native_image_task');save()
        assert all(checks.values()), 'Real image recognition failed'
        native=root/'native';(native/'engine').mkdir(parents=True,exist_ok=True)
        if not (native/'engine/codex.exe').exists():os.link(daily/'engine/codex.exe',native/'engine/codex.exe')
        project=native/'project';project.mkdir(exist_ok=True);result_file=project/'visual-check.txt'
        assert not result_file.exists(), 'Do not reuse a previous native result'
        candidate={**settings,'project':str(project)}
        with patch.object(core,'ROOT',native),patch.object(core.Path,'home',return_value=native/'no-home'):
            core.prepare(candidate);rpc=core.RpcClient(events.put)
        thread=rpc.request('thread/start',{'cwd':str(project),'model':core.HUIHUI_IQ3S_MODEL,
            'modelProvider':'qwen_local','sandbox':'danger-full-access','approvalPolicy':'never',
            'config':core.engine_config(settings)})['thread']
        turn=rpc.request('turn/start',{'threadId':thread['id'],'input':[
            {'type':'text','text':'Read the attached picture. Use one exec_command to write visual-check.txt containing the printed number, color and shape as NUMBER|COLOR|SHAPE in English, then read the file. Do not use image-processing code or inspect filenames to guess. This is a tiny visual readiness check; act directly and give the verified path.'},
            {'type':'localImage','path':str(files[0])}]})['turn']
        report.update(thread_id=thread['id'],turn_id=turn['id']);save()
        deadline=time.monotonic()+90;seen=[];completed=None
        while time.monotonic()<deadline:
            try:event=events.get(timeout=.2)
            except queue.Empty:continue
            seen.append(event)
            if event.get('method')=='turn/completed':completed=event.get('params',{}).get('turn');break
        if completed is None:
            rpc.request('turn/interrupt',{'threadId':thread['id'],'turnId':turn['id']},timeout=10)
            raise TimeoutError('Only the private visual test exceeded its 90-second wait')
        content=result_file.read_text(encoding='utf-8-sig').strip() if result_file.exists() else ''
        checks['native_local_image_file_result']=completed.get('status')=='completed' and all(word in content.lower() for word in shapes[0])
        (root/'native-events.json').write_text(json.dumps(seen,ensure_ascii=False,indent=2),encoding='utf-8')
        report.update(native_status=completed.get('status'),native_file=str(result_file),native_file_content=content,
            phase='complete',ok=all(checks.values()))
    except Exception as error:
        report.update(phase='failed',error=(type(error).__name__+': '+str(error)).replace(settings['api_key'],'[redacted]'))
    finally:
        if rpc:rpc.close()
        report['daily_settings_unchanged']=saved==(daily/'settings.json').read_bytes()
        report['daily_reasoning_budget']=core.active_model().get('reasoning_budget')
        report['ok']=report['ok'] and report['daily_settings_unchanged'] and report['daily_reasoning_budget']==-1
        save();print(json.dumps(report,ensure_ascii=False),flush=True)
    assert report['ok'], 'Inspect verification-vision31-runtime.json'


if __name__=='__main__':main()
