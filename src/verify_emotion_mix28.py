"""Composition and settings preservation checks, not mirrored widget tests."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import verify_emotion27
from emotion_vectors import emotion_state,emotion_args

class Mix(unittest.TestCase):
    def fixture(self,root):
        model=verify_emotion27.EmotionRange().fixture(root)
        path=root/'emotion-vectors/manifest.json';m=json.loads(path.read_text(encoding='utf-8'))
        file=root/'emotion-vectors/docile.gguf';file.write_bytes(b'docile-fixture')
        m['vectors']['docile']={**m['vectors']['angry'],'file':file.name,
            'sha256':hashlib.sha256(file.read_bytes()).hexdigest()}
        path.write_text(json.dumps(m),encoding='utf-8');return model

    def test_two_independent_signed_components_reach_one_csv_argument(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);model=self.fixture(root)
            state=emotion_state(root,model,{'emotion_mode':'angry','emotion_strength':-.5,
                'emotion_secondary_mode':'docile','emotion_secondary_strength':.5})
            args=emotion_args(state)
            self.assertEqual(state['mode'],'mixed');self.assertEqual(len(state['components']),2)
            self.assertEqual(args.count('--control-vector-scaled'),1)
            self.assertIn('angry.gguf:-0.5',args[1]);self.assertIn('docile.gguf:0.5',args[1])
            self.assertIn(',',args[1])

    def test_same_direction_cancellation_addition_and_order_invariance(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);model=self.fixture(root)
            base={'emotion_mode':'angry','emotion_strength':.4,'emotion_secondary_mode':'angry','emotion_secondary_strength':-.4}
            self.assertEqual(emotion_args(emotion_state(root,model,base)),[])
            summed=emotion_state(root,model,{**base,'emotion_secondary_strength':.4})
            self.assertEqual(summed['strength'],.8)  # Never silently normalize the user's sum.
            a={'emotion_mode':'angry','emotion_strength':.1,'emotion_secondary_mode':'docile','emotion_secondary_strength':-.2}
            b={'emotion_mode':'docile','emotion_strength':-.2,'emotion_secondary_mode':'angry','emotion_secondary_strength':.1}
            self.assertEqual(emotion_state(root,model,a)['signature'],emotion_state(root,model,b)['signature'])

    def test_second_channel_works_when_first_off_and_changes_reload_signature(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);model=self.fixture(root)
            old=emotion_state(root,model,{'emotion_mode':'angry','emotion_strength':.002})
            m=json.loads((root/'emotion-vectors/manifest.json').read_text(encoding='utf-8'))
            expected=hashlib.sha256(json.dumps([m['vectors']['angry']['sha256'],.002,16,47]).encode()).hexdigest()
            self.assertEqual(old['signature'],expected)
            second=emotion_state(root,model,{'emotion_mode':'off','emotion_secondary_mode':'docile','emotion_secondary_strength':.002})
            self.assertEqual(second['mode'],'docile')
            combined=emotion_state(root,model,{'emotion_mode':'angry','emotion_secondary_mode':'docile'})
            self.assertNotEqual(old['signature'],combined['signature'])

    def test_second_channel_cannot_bypass_hash_or_layer_guards(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);model=self.fixture(root)
            settings={'emotion_mode':'angry','emotion_secondary_mode':'docile'}
            p=root/'emotion-vectors/manifest.json';m=json.loads(p.read_text(encoding='utf-8'))
            m['vectors']['docile']['layer_range']=[17,47];p.write_text(json.dumps(m),encoding='utf-8')
            with self.assertRaises(ValueError):emotion_state(root,model,settings)
            m['vectors']['docile']['layer_range']=[16,47];p.write_text(json.dumps(m),encoding='utf-8')
            (root/'emotion-vectors/docile.gguf').write_bytes(b'changed')
            with self.assertRaises(ValueError):emotion_state(root,model,settings)

if __name__=='__main__':unittest.main(verbosity=2)
