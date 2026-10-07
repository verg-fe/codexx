import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
import core
from emotion_extract import write_vector
from profiles26_guard import cancellation_covers


class GuardChecks(unittest.TestCase):
    def test_cancel_receipt_is_bound_to_exact_turn_and_closed_processes(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(core,'ROOT',Path(folder)):
            path=Path(folder)/'rollout-known-thread.jsonl'
            data={'authorized_by_user':True,'gui_and_engine_exited':True,'thread_id':'known-thread',
                  'turn_id':'known-turn','gui_pid':123,'engine_pid':456}
            (Path(folder)/'cancelled-migration-20261003.json').write_text(json.dumps(data))
            with patch('profiles26_guard.process_alive',return_value=False):
                self.assertTrue(cancellation_covers(path,'known-turn'))
                self.assertFalse(cancellation_covers(path,'new-turn'))
                self.assertFalse(cancellation_covers(Path(folder)/'other.jsonl','known-turn'))
            with patch('profiles26_guard.process_alive',return_value=True):
                self.assertFalse(cancellation_covers(path,'known-turn'))

    def test_missing_receipt_never_bypasses_turn_guard(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(core,'ROOT',Path(folder)):
            self.assertFalse(cancellation_covers(Path(folder)/'known-thread.jsonl','known-turn'))

    def test_vector_layer_numbers_match_runtime_application(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'vector.gguf'
            write_vector(path,np.array([[11]*8,[22]*8]),[1,2],8,4,'qwen35')
            actual=np.frombuffer(path.read_bytes()[-3*8*4:],dtype='<f4').reshape(3,8)
            np.testing.assert_array_equal(actual,np.array([[11]*8,[22]*8,[0]*8]))


if __name__=='__main__':unittest.main()
