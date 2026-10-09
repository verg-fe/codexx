import queue,unittest
from types import SimpleNamespace
from unittest.mock import patch
import app

class ConnectionRetry(unittest.TestCase):
    def subject(self):return SimpleNamespace(events=queue.Queue(),rpc=None)
    def test_unreadable_model_waits(self):
        obj=self.subject()
        with patch.object(app,'refresh_gateway_for_current_app',side_effect=RuntimeError('模型进程的状态暂时无法读取，请稍后重新打开新版工作台。')):
            app.App.connect(obj)
        self.assertEqual(obj.events.get()['local'],'connection_wait');self.assertEqual(obj.connection_retry_count,1)
    def test_retry_recovers(self):
        obj=self.subject();obj.connection_retry_count=2
        with patch.object(app,'refresh_gateway_for_current_app'),patch.object(app,'RpcClient',return_value=SimpleNamespace(proxy_error=False)):
            app.App.connect(obj)
        self.assertEqual(obj.events.get()['local'],'connected');self.assertEqual(obj.connection_retry_count,0)
    def test_unknown_port_owner_is_not_retried(self):
        obj=self.subject()
        with patch.object(app,'refresh_gateway_for_current_app',side_effect=RuntimeError('占用者不是可确认的 MyCodex 接口。')):
            app.App.connect(obj)
        self.assertEqual(obj.events.get()['local'],'error')
    def test_retries_are_bounded(self):
        obj=self.subject();obj.connection_retry_count=60
        with patch.object(app,'refresh_gateway_for_current_app',side_effect=RuntimeError('旧会话仍在推理')):
            app.App.connect(obj)
        self.assertEqual(obj.events.get()['local'],'error')

if __name__=='__main__':unittest.main(verbosity=2)
