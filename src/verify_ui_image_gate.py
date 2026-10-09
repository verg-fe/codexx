import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
import ui_image_gate as gate


class ImageGate(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=r'G:\LocalCodex-work')
        self.root=Path(self.tmp.name)
        self.patcher=patch.object(gate,'JOBS',self.root);self.patcher.start()
        self.image=self.root/'screen.png';self.image.write_bytes(b'\x89PNG\r\n\x1a\nfixture')
        self.state={'snapshot_id':'a'*32,'created_at':time.time(),'expires_after_seconds':180,
                    'width':1080,'height':2400,'candidates':[{'id':1,'text':'返回','description':'','resource_id':'back','center':[60,120],'bounds':[0,60,120,180],'clickable':True}]}
        (self.root/('a'*32+'.json')).write_text(json.dumps(self.state),encoding='utf-8')
        gate.register_snapshot(self.image,self.state)
    def tearDown(self):
        self.patcher.stop();self.tmp.cleanup()
    def body(self):
        return {'input':[{'type':'function_call','call_id':'1','name':'view_image','arguments':json.dumps({'path':str(self.image)})},
                         {'type':'function_call_output','call_id':'1','output':[{'type':'input_image','image_url':'fixture'}]}]}
    def test_fresh_screenshot_becomes_real_control_text(self):
        body=self.body();self.assertEqual(gate.defer_ui_tool_images(body),1)
        block=body['input'][1]['output'][0];self.assertEqual(block['type'],'input_text');self.assertIn('返回',block['text'])
    def test_explicit_vision_fallback_keeps_image(self):
        gate.request_vision(self.image,'Unknown icon after control lookup')
        self.assertEqual(gate.defer_ui_tool_images(self.body()),0)
    def test_changed_file_cannot_reuse_permission(self):
        gate.request_vision(self.image,'Unknown icon');self.image.write_bytes(b'\x89PNG\r\n\x1a\nchanged')
        self.assertEqual(gate.defer_ui_tool_images(self.body()),1)
        self.assertNotIn('返回',gate.image_control_text(self.image))
    def test_expired_controls_do_not_claim_current_page(self):
        self.state['created_at']=time.time()-181
        (self.root/('a'*32+'.json')).write_text(json.dumps(self.state),encoding='utf-8')
        self.assertNotIn('返回',gate.image_control_text(self.image))
    def test_user_attachment_untouched(self):
        body={'input':[{'role':'user','content':[{'type':'input_image','image_url':'fixture'}]}]}
        self.assertEqual(gate.defer_ui_tool_images(body),0)
    def test_observed_prefix_unchanged(self):
        body=self.body();body['input'].append({'role':'assistant','content':[]})
        self.assertEqual(gate.defer_ui_tool_images(body),0)
    def test_photo_outside_android_roots_untouched(self):
        photo=self.root.parent/'gate-photo-test.png';photo.write_bytes(b'fixture')
        try:self.assertIsNone(gate.image_control_text(photo))
        finally:photo.unlink()
    def test_request_requires_reason_and_android_path(self):
        with self.assertRaises(ValueError):gate.request_vision(self.image,'')
        with self.assertRaises(ValueError):gate.request_vision(self.root.parent/'photo.png','unknown')

if __name__=='__main__':unittest.main(verbosity=2)
