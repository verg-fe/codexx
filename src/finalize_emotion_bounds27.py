"""Confirm full EOS records and refine boundaries under the user's selected prompt profile."""
import json
import math
import time
import core
import verify_emotion_bounds27 as test
from profiles26_guard import guard

def main():
    report=json.loads(test.REPORT.read_text(encoding='utf-8'))
    assert report['ok'] and report['phase']=='complete'
    proc=None
    with core.model_lock():
        try:
            state=guard()
            if not state['safe']:raise RuntimeError(state['reason'])
            if core.server_ready():raise RuntimeError('Daily model now running; did not interrupt it')
            settings=core.load_settings();profile=settings.get('directive_mode','native')
            saved=(core.ROOT/'settings.json').read_bytes()
            manifest=json.loads((core.ROOT/'emotion-vectors/manifest.json').read_text(encoding='utf-8'))
            report['selected_directive']=profile
            for mode in test.MODES:
                entry=manifest['vectors'][mode];record=report['vectors'][mode]
                proc=test.start(entry,.05,mode+'-005-full',profile)
                try:
                    prompt='17 * 19 = ? Return only the integer.'
                    rawfile=test.OUT/(mode+'-005.raw.json')
                    raw=json.loads(rawfile.read_text(encoding='utf-8'))
                    # Actual low-level stop reason, no artificial 16-token stop.
                    for thinking,limit in ((False,128),(True,64)):
                        formatted=test.request('/apply-template',{'messages':[{'role':'user','content':prompt}],
                            'chat_template_kwargs':{'enable_thinking':thinking}})['prompt']
                        if not thinking and formatted.endswith('<think>\n'):formatted+='</think>\n\n'
                        body={'prompt':formatted,'temperature':0,'n_predict':limit,'return_tokens':True,
                              'n_probs':5,'post_sampling_probs':False,'cache_prompt':False}
                        response=test.request('/completion',body)
                        key='selected_profile_thinking' if thinking else 'selected_profile_no_thinking'
                        raw[key]={'directive':profile,'response':response}
                        print(json.dumps({'mode':mode,'strength':.05,'thinking':thinking,
                            'stop_type':response.get('stop_type'),'tokens':response.get('tokens'),
                            'content':response.get('content'),'predicted':response.get('tokens_predicted')},ensure_ascii=False),flush=True)
                    test.save(rawfile,raw)
                    record['raw005']['full_raw_file']=str(rawfile)
                finally:test.stop(proc);proc=None
                cases=[]
                def case(strength,label,features=False):
                    nonlocal proc
                    try:
                        proc=test.start(entry,strength,label,profile)
                        result=test.suite(label,features)
                    finally:test.stop(proc);proc=None
                    result.update(strength=strength,directive=profile)
                    print(json.dumps({'mode':mode,'selected_profile':profile,'strength':strength,'pass':result['pass']},ensure_ascii=False),flush=True)
                    cases.append(result)
                    return result
                if record['selected_profile_check']['pass']:
                    low=record['observed_pass_strength'];upper=record['observed_fail_strength']
                    boundary=record['selected_profile_check']
                    selected_upper_probed=False
                else:
                    upper=record['observed_pass_strength']
                    seed=case(.002,mode+'-current-002')
                    if not seed['pass']:raise RuntimeError('Previously used strength fails selected-profile checks: '+mode)
                    low=.002;selected_upper_probed=True
                    while upper-low>test.RESOLUTION:
                        mid=round((low+upper)/2,7)
                        result=case(mid,mode+'-current-'+str(mid))
                        if result['pass']:low=mid
                        else:upper=mid
                    boundary=case(low,mode+'-current-final',True)
                    if not boundary['pass']:raise RuntimeError('Boundary final feature check failed: '+mode)
                # Use a strength selectable by the 0.0001-step slider and verify that exact value.
                low=math.floor(low*10000+1e-8)/10000
                boundary=case(low,mode+'-current-slider-final',True)
                if not boundary['pass']:raise RuntimeError('Selectable boundary feature check failed: '+mode)
                # Independent clean-load repeat at the usable boundary, including tools and images.
                repeat=case(low,mode+'-current-repeat',True)
                if not repeat['pass']:raise RuntimeError('Boundary repeat failed under the selected profile: '+mode)
                record['current_profile_boundary']={'observed_pass_strength':low,'upper_strength':upper,
                    'upper_probed_in_this_profile':selected_upper_probed,'checks':boundary['checks'],
                    'repeat_passed':True,'samples':cases,'directive':profile,
                    'note':'Observed local boundary, monotonicity and long-task quality not guaranteed'}
                # Keep all prior evidence and only update the metadata for the current model vectors.
                entry['boundary_check']={**record['current_profile_boundary'],'boundary_repeat_passed':True,
                    'observed_fail_strength':upper if selected_upper_probed else None,
                    'report':str(test.REPORT),'backend':core.selected_backend()}
                entry['tested_strength']=low
                test.save(test.REPORT,report)
            report['raw005_full_verified']=True
            report['current_profile_boundaries_verified']=True
            report['daily_settings_unchanged']=saved==(core.ROOT/'settings.json').read_bytes()
            if not report['daily_settings_unchanged']:raise RuntimeError('User settings changed during tests; preserve their new choice')
            test.save(core.ROOT/'emotion-vectors/manifest.json',manifest)
        finally:
            test.stop(proc);test.save(test.REPORT,report)
    print(json.dumps({'ok':True,'current_profile_bounds':{m:r['current_profile_boundary']['observed_pass_strength']
        for m,r in report['vectors'].items()}},ensure_ascii=False),flush=True)

if __name__=='__main__':main()
