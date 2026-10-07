"""Real private native Codex file task at the preserved daily emotion setting."""
import json
import urllib.request
from unittest.mock import patch
import core
import gateway
import verify_emotion_bounds27 as test
from verify_profiles26_runtime import native_file_check
from profiles26_guard import guard

def main():
    report={'ok':False,'phase':'preflight','daily_settings_changed':False,'model_requests_are_private':True}
    proc=None
    with core.model_lock():
        try:
            state=guard()
            if not state['safe']:raise RuntimeError(state['reason'])
            if core.server_ready():raise RuntimeError('Daily model now running; kept it intact')
            saved=(core.ROOT/'settings.json').read_bytes();settings=core.load_settings()
            manifest=json.loads((core.ROOT/'emotion-vectors/manifest.json').read_text(encoding='utf-8'))
            mode=settings.get('emotion_mode','off');strength=settings.get('emotion_strength',.002)
            proc=test.start(manifest['vectors'].get(mode),strength,'preserved-daily-native',settings.get('directive_mode','native'))
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
                settings_unchanged=True,emotion_mode=mode,emotion_strength=strength,
                directive_mode=settings.get('directive_mode'),backend=core.selected_backend(),
                timings=response.get('timings'),test_only_generation_caps=True,real_model_precision_changed=False)
        except Exception as error:
            report.update(phase='failed',error=str(error));raise
        finally:
            test.stop(proc)
            test.save(core.ROOT/'verification-emotion27-native.json',report)
    print(json.dumps(report,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
