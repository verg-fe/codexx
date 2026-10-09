import queue
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import app

class Button:
    def __init__(self):self.states=[]
    def configure(self,**state):self.states.append(state)

class ReleaseChecks(unittest.TestCase):
    def make(self):
        return SimpleNamespace(busy=False,loading_model=False,unload_button=Button(),
                               events=queue.Queue(),background=lambda fn:fn())
    def test_success_feedback(self):
        owner=self.make()
        with patch.object(app,'server_ready',return_value=False),patch.object(app,'stop_model') as stop:
            app.App.unload_model(owner)
        stop.assert_called_once()
        self.assertEqual(owner.events.get(),{'local':'model_unloaded','ok':True})
        self.assertEqual(owner.unload_button.states[0]['state'],'disabled')
    def test_failure_feedback(self):
        owner=self.make()
        with patch.object(app,'server_ready',return_value=False),patch.object(app,'stop_model',side_effect=RuntimeError('release failed')):
            app.App.unload_model(owner)
        self.assertFalse(owner.events.get()['ok'])
    def test_duplicate_release_ignored(self):
        owner=self.make();owner.unloading_model=True
        with patch.object(app,'stop_model') as stop:app.App.unload_model(owner)
        stop.assert_not_called()

if __name__=='__main__':unittest.main()
