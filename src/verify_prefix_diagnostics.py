import unittest
from unittest.mock import patch
import prefix_diagnostics as p
import core

class PrefixChecks(unittest.TestCase):
    def test_prefix_and_changed_fields(self):
        with patch.object(p,'_previous',None):
            a=p.observe([1,2,3],{'instructions':'stable','tools':[]})
            self.assertFalse(a['text_prefix_previous_available'])
            b=p.observe([1,2,4],{'instructions':'stable','tools':[]})
            self.assertEqual(b['text_prefix_common_tokens'],2)
            self.assertEqual(b['text_prefix_changed_fields'],[])
            c=p.observe([1,2,4],{'instructions':'new','tools':[]})
            self.assertEqual(c['text_prefix_changed_fields'],['instructions'])
            self.assertNotIn('new',str(c))
    def test_model_checkpoint_configuration(self):
        args=core.model_args(core.selected_model(),95000)
        self.assertEqual(args[args.index('--ctx-checkpoints')+1],'16')
        self.assertEqual(args[args.index('-ctk')+1],'q4_0')
    def test_old_policy_is_not_accepted(self):
        record={'prompt_cache_ram_mib':8192,'prompt_cache_idle_slots':True,
                'prompt_cache_enabled':True,'prompt_cache_directory':str(core.PROMPT_CACHE_DIRECTORY)}
        self.assertFalse(core.prompt_cache_policy_matches(record))
        record['prompt_cache_checkpoints']=16
        self.assertTrue(core.prompt_cache_policy_matches(record))

if __name__=='__main__':unittest.main()
