from pathlib import Path
r=Path(__file__).parent
s=(r/'stop_for_moe70ram35.py').read_text(encoding='utf-8').replace('verification-project/moe70ram35','verification-project/moe35-functional')
(r/'stop_for_moe35_functional.py').write_text(s,encoding='utf-8')
s=(r/'verify_moe70ram35.py').read_text(encoding='utf-8').replace('verification-project/moe70ram35','verification-project/moe35-functional').replace('verification-moe70ram35.json','verification-moe35-functional.json')
anchor="case['success']=True;report['success']=True"
inject='''from unittest.mock import patch
                    import verify_kv20 as kv
                    def functional_request(route,body=None,timeout=240):
                        if body is not None:body={**body,'max_tokens':384}
                        return call(route,body,timeout=timeout)
                    with patch.object(kv,'request',side_effect=functional_request):
                        case['functional']=kv.functions_check(False)
                    '''
assert anchor in s
s=s.replace(anchor,inject+anchor)
(r/'verify_moe35_functional.py').write_text(s,encoding='utf-8')
