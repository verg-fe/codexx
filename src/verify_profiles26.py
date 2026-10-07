"""Profile protocol invariants and mathematical checks; never load model weights."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET
import numpy as np
sys.path.insert(0,str(Path(r'D:\LocalCodex\verification-deps\native25')))
from jinja2 import Environment
import core
from directive_profiles import DIRECTIVE_MODES,build_directive,selected_directive
from emotion_extract import derive_vectors,write_vector,corpus
from emotion_vectors import emotion_state,emotion_args,model_fingerprint
from gguf_info import read_metadata
from model_templates import native_thinking_template,profile_template,ensure_profile_template


class Profiles(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model=core.model_file(core.MODEL);cls.before=cls.model.stat()
        cls.original=read_metadata(cls.model)['tokenizer.chat_template']
        cls.native,cls.old=native_thinking_template(cls.original)

    @classmethod
    def tearDownClass(cls):
        after=cls.model.stat();assert (after.st_size,after.st_mtime_ns)==(cls.before.st_size,cls.before.st_mtime_ns)

    def render(self,template,messages,tools=(),thinking=True):
        env=Environment();env.globals['raise_exception']=lambda x:(_ for _ in ()).throw(ValueError(x))
        return env.from_string(template).render(messages=messages,tools=tools,add_generation_prompt=True,
            enable_thinking=thinking,preserve_thinking=True,reasoning_effort='medium',add_vision_id=False)

    def test_replacement_keeps_tools_history_images_and_think_boundary(self):
        messages=[{'role':'system','content':'BASE_SYSTEM'},{'role':'user','content':[
            {'type':'text','text':'Describe this picture'},{'type':'image','image':'fixture'}]},
            {'role':'assistant','content':'','reasoning_content':'OLD_REASONING',
             'tool_calls':[{'function':{'name':'ping','arguments':{'message':'ok'}}}]},
            {'role':'tool','content':'REAL_RESULT'}]
        tools=[{'type':'function','function':{'name':'ping','parameters':{'type':'object','properties':{}}}}]
        before=self.render(self.original,messages,tools)
        for mode in ('angry','desperate','obedient','open_xml','custom'):
            settings={'directive_mode':mode,'directive_custom_tag':'my_test',
                      'directive_custom_text':'Keep {{ untouched }} & <quoted> data.'}
            with self.subTest(mode=mode):
                result=self.render(profile_template(self.original,settings),messages,tools)
                self.assertEqual(result,before.replace(self.old,build_directive(settings),1))
                self.assertNotIn(self.old,result);self.assertIn('OLD_REASONING',result)
                self.assertIn('<function=ping>',result);self.assertTrue(result.endswith('<think>\n'))
                self.assertIn('<|vision_start|>',result)
                xml=build_directive(settings).split('\n',2)[2];ET.fromstring(xml)
        self.assertEqual(profile_template(self.original,{'directive_mode':'legacy'}),self.original)
        self.assertEqual(profile_template(self.original,{'directive_mode':'native'}),self.native)

    def test_custom_data_cannot_execute_jinja_or_break_xml(self):
        s={'directive_mode':'custom','directive_custom_tag':'my_test',
           'directive_custom_text':'{{ raise_exception("executed") }} </my_test> & "quoted"'}
        result=self.render(profile_template(self.original,s),[{'role':'user','content':'Hi'}])
        self.assertIn('{{ raise_exception("executed") }}',result)
        xml=ET.fromstring(build_directive(s).split('\n',2)[2])
        self.assertEqual(xml.find('custom_instructions/my_test').text.strip(),s['directive_custom_text'])
        for tag in ('bad name','x><tool_call','1abc','x'*65):
            with self.assertRaises(ValueError):build_directive({**s,'directive_custom_tag':tag})
        with self.assertRaises(ValueError):build_directive({**s,'directive_custom_text':''})

    def test_settings_validation_precedes_any_saved_state(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(core,'ROOT',Path(folder)):
            with self.assertRaises(ValueError):core.prepare({'directive_mode':'custom'})
            self.assertFalse((Path(folder)/'settings.json').exists())
        self.assertEqual(selected_directive({}),'legacy')
        self.assertEqual(selected_directive({'jack_xml_enabled':False}),'native')

    def test_hash_change_causes_reload_and_native_parameters_stay_identical(self):
        s={**core.load_settings(),'emotion_mode':'off','directive_mode':'native','jack_xml_enabled':False}
        with tempfile.TemporaryDirectory() as folder,patch.object(core,'ROOT',Path(folder)):
            with patch.object(core,'load_settings',return_value=s):base=core.model_args(core.MODEL,core.GPU_CONTEXT_LIMIT)
            for mode in ('angry','desperate','obedient','open_xml'):
                chosen={**s,'directive_mode':mode}
                with patch.object(core,'load_settings',return_value=chosen):args=core.model_args(core.MODEL,core.GPU_CONTEXT_LIMIT)
                def strip_template(values):
                    index=values.index('--chat-template-file');return values[:index]+values[index+2:]
                self.assertEqual(strip_template(args),strip_template(base))
                a=ensure_profile_template(folder,self.model,chosen)
                b=ensure_profile_template(folder,self.model,{**chosen,'directive_mode':'native'})
                self.assertNotEqual(a['sha256'],b['sha256'])
            bad=ensure_profile_template(folder,self.model,{**s,'directive_mode':'obedient'})
            Path(bad['file']).write_text('changed',encoding='utf-8')
            with self.assertRaises(ValueError):ensure_profile_template(folder,self.model,{**s,'directive_mode':'obedient'})

    def test_emotion_vector_identity_validation_and_disabled_default(self):
        self.assertEqual(emotion_args(emotion_state('.',self.model,{})),[])
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);directory=root/'emotion-vectors';directory.mkdir()
            with self.assertRaises(ValueError):emotion_state(root,self.model,{'emotion_mode':'angry'})
            path=directory/'angry.gguf';write_vector(path,np.ones((2,8)),[1,2],8,4,'qwen35')
            m={'model':model_fingerprint(self.model),'main_layers':4,'vectors':{'angry':{
                'file':path.name,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'layer_range':[1,2],'runtime_verified':False}}}
            mp=directory/'manifest.json';mp.write_text(json.dumps(m),encoding='utf-8')
            with self.assertRaises(ValueError):emotion_state(root,self.model,{'emotion_mode':'angry'})
            m['vectors']['angry']['runtime_verified']=True;mp.write_text(json.dumps(m),encoding='utf-8')
            state=emotion_state(root,self.model,{'emotion_mode':'angry','emotion_strength':.05})
            self.assertIn(':0.05',emotion_args(state)[1])
            self.assertNotIn(':',emotion_args(state)[1].rsplit(':',1)[0])
            with self.assertRaises(ValueError):emotion_state(root,self.model,{'emotion_mode':'angry','backend':'hip'})
            path.write_bytes(path.read_bytes()+b'changed')
            with self.assertRaises(ValueError):emotion_state(root,self.model,{'emotion_mode':'angry'})

    def test_pca_removes_planted_topic_confound_and_keeps_emotion_signal(self):
        labels=[];held=[];means=[];norms=[]
        names=['angry','desperate','calm','docile','joyful','neutral']
        for topic in range(10):
            for index,name in enumerate(names):
                a=np.zeros((2,8));a[:,0]=topic*5
                if name!='neutral':a[:,index+1]=3
                labels.append(name);held.append(topic>=8);means.append(a);norms.append([12,12])
        vectors,scores,pcs=derive_vectors(means,norms,labels,held)
        self.assertEqual(pcs,[1,1])
        for name,vector in vectors.items():
            np.testing.assert_allclose(vector[:,0],0,atol=1e-6)
            np.testing.assert_allclose(np.linalg.norm(vector,axis=1),12,rtol=1e-6)
            self.assertEqual(scores[name]['pairwise_separation'],1)
        rows=corpus();self.assertEqual(len(rows),180)
        self.assertEqual({r['topic'] for r in rows if r['holdout']},set(range(24,30)))


if __name__=='__main__':unittest.main(verbosity=2)
