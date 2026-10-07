"""Record real startup evidence without account credentials or request contents."""
import json
import core

def main():
    settings=core.load_settings();live=core.active_model()
    props=core.api('/props');defaults=props.get('default_generation_settings',{})
    params=defaults.get('params',defaults)
    state=dict(gateway=core.gateway_api('/health'),model=core.api('/health'),pid=live.get('pid'),
        reasoning_budget=live.get('reasoning_budget'),runtime_matches=core.runtime_matches_settings(live,settings),
        generation_guard=settings['generation_guard'],reasoning_effort=settings.get('reasoning_effort'),
        engine_limits=core.engine_limits(settings),
        runtime_sampler={k:params.get(k) for k in ('temperature','top_p','top_k','min_p','presence_penalty','repeat_penalty')},
        model_directory=str(core.model_directory(settings)),fresh_speed_test=False,
        historical_decode_median_tps=30.67,historical_decode_samples=95,
        source='Existing model.log: latest 100 generation records, exclude records with fewer than 100 output tokens')
    path=core.ROOT/'deployment-thinking38.json'
    record=json.loads(path.read_text(encoding='utf-8'));record['startup']=state
    path.write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(state,ensure_ascii=False))

if __name__=='__main__':main()
