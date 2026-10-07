"""Real native Codex tools/file write using the composed vectors from core.model_args."""
import hashlib
import json
import os
import subprocess
import time
import urllib.request
from unittest.mock import patch
import core
import gateway
import verify_emotion_bounds27 as test
from verify_profiles26_runtime import native_file_check
from profiles26_guard import guard

def main():
    report={'ok':False,'phase':'preflight','test_only_generation_caps':True};proc=None
    with core.model_lock():
        try:
            state=guard()
            if not state['safe']:raise RuntimeError(state['reason'])
            if core.server_ready():raise RuntimeError('Daily model running; kept it intact')
            saved=(core.ROOT/'settings.json').read_bytes();settings=core.load_settings()
            private={**settings,'emotion_mode':'joyful','emotion_strength':.002,
                'emotion_secondary_mode':'sad','emotion_secondary_strength':.002}
            with patch.object(core,'load_settings',return_value=private):
                args=core.model_args(core.MODEL,8192)
            assert args.count('--control-vector-scaled')==1
            vector_argument=args[args.index('--control-vector-scaled')+1]
            assert 'joyful.gguf:0.002' in vector_argument and 'sad.gguf:0.002' in vector_argument
            args[args.index('--port')+1]=str(test.PORT)
            cache=core.ROOT/'cache/emotion28-private';cache.mkdir(parents=True,exist_ok=True)
            args[args.index('--slot-save-path')+1]=str(cache)
            with (core.ROOT/'logs/emotion28-native-backend.log').open('w',encoding='utf-8') as log:
                proc=subprocess.Popen(args,env=core.runtime_environment(),cwd=core.runtime_directory(),
                    stdin=subprocess.DEVNULL,stdout=log,stderr=log,creationflags=core.NO_WINDOW)
            until=time.monotonic()+100
            while True:
                if proc.poll() is not None:raise RuntimeError('Private model failed to start')
                try:
                    if test.request('/health',timeout=2).get('status')=='ok':break
                except (OSError,RuntimeError,ValueError):pass
                if time.monotonic()>until:raise RuntimeError('Private model readiness timeout')
                time.sleep(.25)
            response=test.chat('17 * 19 = ? Return only the integer.',max_tokens=256,
                chat_template_kwargs={'enable_thinking':True,'reasoning_effort':'low'})
            message=response['choices'][0]['message']
            assert '323' in (message.get('content') or '') and (message.get('reasoning_content') or '').strip()
            constructor=urllib.request.Request
            def local_request(url,*args,**kwargs):
                if isinstance(url,str) and url.startswith('http://127.0.0.1:8080'):
                    url=url.replace('http://127.0.0.1:8080','http://127.0.0.1:8082',1)
                return constructor(url,*args,**kwargs)
            with patch.object(gateway.urllib.request,'Request',side_effect=local_request):
                result=native_file_check(core.ROOT)
            assert saved==(core.ROOT/'settings.json').read_bytes()
            report.update(ok=True,phase='complete',native_thinking_and_text=True,native_file=result,
                daily_settings_sha256=hashlib.sha256(saved).hexdigest(),settings_unchanged=True,
                daily_model_stopped=True,components=[['joyful',.002],['sad',.002]],
                vector_argument=vector_argument,backend=core.selected_backend(),timings=response.get('timings'),
                weights_modified=False)
        except Exception as error:report.update(phase='failed',error=str(error));raise
        finally:
            test.stop(proc);test.save(core.ROOT/'verification-emotion28-native.json',report)
    print(json.dumps(report,ensure_ascii=False),flush=True)

if __name__=='__main__':main()
