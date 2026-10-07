"""Regression checks for experimental range, advisory boundaries and vector integrity."""
import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import emotion_vectors as ev
import core

class EmotionRange(unittest.TestCase):
    def fixture(self,root):
        model=root/'model.gguf';model.write_bytes(b'fixture-model')
        folder=root/'emotion-vectors';folder.mkdir()
        vector=folder/'angry.gguf';vector.write_bytes(b'fixture-vector')
        manifest={'model':ev.model_fingerprint(model),'main_layers':64,'vectors':{'angry':{
            'file':vector.name,'sha256':hashlib.sha256(vector.read_bytes()).hexdigest(),
            'runtime_verified':True,'verified_backends':['vulkan'],'tested_strength':.002,
            'layer_range':[16,47],'boundary_check':{'observed_pass_strength':.01,
            'observed_fail_strength':.0104,'boundary_repeat_passed':True}}}}
        (folder/'manifest.json').write_text(json.dumps(manifest),encoding='utf-8')
        return model

    def test_signed_range_is_authorized_experimental_and_over_range_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);model=self.fixture(root)
            for value in (-.5,-.05,0,.002,.01,.05,.5):
                state=ev.emotion_state(root,model,{'emotion_mode':'angry','emotion_strength':value})
                self.assertEqual(state.get('strength',0),value)
            for value in (-.5001,.5001,float('nan'),float('inf')):
                with self.assertRaises(ValueError):ev.emotion_state(root,model,{'emotion_mode':'angry','emotion_strength':value})

    def test_range_does_not_bypass_backend_identity_or_integrity(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);model=self.fixture(root)
            with self.assertRaises(ValueError):ev.emotion_state(root,model,{'emotion_mode':'angry','emotion_strength':.05,'backend':'hip'})
            model.write_bytes(b'changed-model')
            with self.assertRaises(ValueError):ev.emotion_state(root,model,{'emotion_mode':'angry','emotion_strength':.05})

    def test_advisory_shows_measured_bounds_and_unverified_high_strength(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);self.fixture(root)
            self.assertIn('0.0100',ev.emotion_hint(root,'angry',.002))
            self.assertIn('0.0104',ev.emotion_hint(root,'angry',.002))
            self.assertIn('高于短测通过点',ev.emotion_hint(root,'angry',.05))
            self.assertIn('已关闭',ev.emotion_hint(root,'off',.05))

    def test_model_arguments_preserve_daily_policy_while_only_vector_scale_changes(self):
        settings=core.load_settings()
        with patch.object(core,'load_settings',return_value=settings):base=core.model_args(core.MODEL,8192)
        changed={**settings,'emotion_strength':.05}
        with patch.object(core,'load_settings',return_value=changed):high=core.model_args(core.MODEL,8192)
        index=base.index('--control-vector-scaled')+1
        self.assertNotEqual(base[index],high[index])
        base[index]=high[index];self.assertEqual(base,high)
        self.assertEqual(high[high.index('--reasoning-budget')+1],'-1')
        self.assertEqual(high[high.index('-n')+1],'-1')

if __name__=='__main__':unittest.main(verbosity=2)
