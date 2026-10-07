import base64
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

from conversations import ConversationStore
import gateway


class MediaAndDeletionChecks(unittest.TestCase):
    def test_webp_transcodes_without_losing_pixels_or_alpha(self):
        image=Image.new('RGBA',(23,17),(200,50,10,120))
        buffer=io.BytesIO();image.save(buffer,format='WEBP',lossless=True)
        url='data:image/webp;base64,'+base64.b64encode(buffer.getvalue()).decode()
        body={'input':[{'role':'user','content':[{'type':'input_image','image_url':url}]},
            {'type':'function_call_output','output':[{'type':'input_image','image_url':url}]}]}
        self.assertEqual(gateway.normalize_media(body),2)
        converted=body['input'][0]['content'][0]['image_url']
        self.assertTrue(converted.startswith('data:image/png;base64,'))
        loaded=Image.open(io.BytesIO(base64.b64decode(converted.split(',',1)[1])))
        self.assertEqual(loaded.size,image.size)
        self.assertEqual(loaded.getpixel((0,0)),image.getpixel((0,0)))
        self.assertEqual(gateway.normalize_media(body),0)

    def test_chat_image_url_objects_and_invalid_images(self):
        image=Image.new('RGB',(2,2),'red')
        buffer=io.BytesIO();image.save(buffer,format='WEBP',lossless=True)
        body={'messages':[{'role':'user','content':[{'type':'image_url','image_url':{
            'url':'data:image/webp;base64,'+base64.b64encode(buffer.getvalue()).decode()}}]}]}
        self.assertEqual(gateway.normalize_media(body),1)
        with self.assertRaisesRegex(ValueError,'图片附件无法解析'):
            gateway.compatible_image_url('data:image/webp;base64,broken')

    def test_delete_restore_keep_other_chats_and_exact_transcript(self):
        with tempfile.TemporaryDirectory() as root:
            store=ConversationStore(root)
            ids=['01a0fe00-fb92-7b23-bd08-d463427b24ce','01a0fdec-8b12-7263-9310-4405245d9350']
            sessions=[{'id':x,'title':x,'project':'test'} for x in ids]
            store.write(store.index,sessions)
            transcript='历史内容\n<完整内容>\n'
            store.path_for(ids[0]).write_text(transcript,encoding='utf-8')
            store.delete(ids[0])
            self.assertEqual(store.sessions(),sessions[1:])
            self.assertFalse(store.path_for(ids[0]).exists())
            self.assertEqual(store.path_for(ids[0],True).read_text(encoding='utf-8'),transcript)
            self.assertEqual(ConversationStore(root).deleted_sessions()[-1]['session']['id'],ids[0])
            store.restore(ids[0])
            self.assertEqual(store.sessions(),sessions)
            self.assertEqual(store.path_for(ids[0]).read_text(encoding='utf-8'),transcript)
            self.assertEqual(store.deleted_sessions(),[])

    def test_index_failure_rolls_back_file_move(self):
        with tempfile.TemporaryDirectory() as root:
            store=ConversationStore(root)
            sid='01a0fe00-fb92-7b23-bd08-d463427b24ce'
            sessions=[{'id':sid,'title':'keep','project':'test'}]
            store.write(store.index,sessions)
            store.path_for(sid).write_text('KEEP',encoding='utf-8')
            original=store.write
            def fail_index(path,data):
                if path==store.index:raise OSError('simulated write failure')
                return original(path,data)
            with patch.object(store,'write',side_effect=fail_index):
                with self.assertRaises(OSError):store.delete(sid)
            self.assertEqual(store.path_for(sid).read_text(),'KEEP')
            self.assertEqual(store.sessions(),sessions)
            self.assertEqual(store.deleted_sessions(),[])

    def test_invalid_ids_and_corrupt_indexes_are_not_overwritten(self):
        with tempfile.TemporaryDirectory() as root:
            store=ConversationStore(root)
            with self.assertRaises(ValueError):store.path_for('../other.txt')
            store.root.mkdir();store.index.write_text('broken',encoding='utf-8')
            with self.assertRaises(ValueError):store.delete('01a0fe00-fb92-7b23-bd08-d463427b24ce')
            self.assertEqual(store.index.read_text(),'broken')


if __name__=='__main__':unittest.main(verbosity=2)
