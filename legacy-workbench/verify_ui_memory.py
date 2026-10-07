"""Check bounded native display, disk history, cleanup and approval fallback."""
import json
import uuid
from app import App, DISPLAY_CHARS
from core import ROOT
from verify_upgrade import memory
import os

app = App(smoke=True)
app.withdraw()
app.thread_id = str(uuid.uuid4())
path = ROOT / 'conversations' / (app.thread_id + '.txt')
samples = []
expected = []
try:
    for n in range(8):
        item_id = f'test-message-{n}'
        text = f'RECORD-{n}\n' + ('bounded display memory exercise\n' * 7000)
        expected.append(f'RECORD-{n}')
        app.handle_event({'method':'item/agentMessage/delta',
                         'params':{'threadId':app.thread_id,'itemId':item_id,'delta':text}})
        # An interrupted message has no completed item: compaction must still release it.
        app.handle_event({'method':'item/completed', 'params':{'threadId':app.thread_id,
                          'item':{'id':f'compact-{n}', 'type':'contextCompaction'}}})
        app.handle_event({'method':'turn/completed', 'params':{'threadId':app.thread_id,
                          'turn':{'id':f'turn-{n}', 'error':None}}})
        app.update()
        assert not app.message_buffers
        assert not app.transcript
        count = int(app.chat._textbox.count('1.0','end-1c','chars')[0])
        assert count <= DISPLAY_CHARS, count
        samples.append(memory(os.getpid()))
    history = path.read_text(encoding='utf-8')
    assert all(history.count(marker) == 1 for marker in expected), 'Lost or duplicate disk history'
    class FakeRpc:
        def __init__(self): self.sent=[]
        def send(self, message): self.sent.append(message)
    app.rpc = FakeRpc()
    app.handle_event({'id':1,'method':'item/commandExecution/requestApproval','params':{}})
    app.handle_event({'id':2,'method':'item/fileChange/requestApproval','params':{}})
    assert [m['result']['decision'] for m in app.rpc.sent] == ['accept','accept']
    growth = round(samples[-1]['private_mib'] - samples[1]['private_mib'],2)
    assert growth < 32, f'Unexpected native UI memory growth: {growth} MiB'
    report={'ok':True,'rounds':8,'display_char_limit':DISPLAY_CHARS,
            'disk_history_bytes':path.stat().st_size,'memory_samples':samples,
            'private_growth_after_warmup_mib':growth,'auto_approve_fallback':True}
    (ROOT/'verification-ui-memory.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))
finally:
    app.destroy()
    path.unlink(missing_ok=True)
