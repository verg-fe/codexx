import base64,json,io,unittest,tempfile
from pathlib import Path
from unittest.mock import patch
from PIL import Image
import android_coordinates as a
import screen_coordinates as s
import gateway

class CoordinateTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=r'G:\LocalCodex\android-ui-jobs')
        self.root=Path(self.tmp.name);self.image=self.root/'screen.png'
        Image.new('RGB',(1080,2400),'white').save(self.image)
    def tearDown(self):self.tmp.cleanup()
    def test_resized_mapping(self):
        r=s.map_point(str(self.image),845,150,922,2048)
        self.assertEqual(r['image_point'],[989,175])
    def test_normalized(self):self.assertEqual(s.map_point(str(self.image),.5,.25)['image_point'],[540,600])
    def test_crop(self):self.assertEqual(s.map_point(str(self.image),.5,.5,crop=[100,200,500,800])['image_point'],[300,500])
    def test_negative_monitor_origin(self):
        r=s.map_point(str(self.image),.5,.5,physical_capture_bounds=[-1920,0,0,1080])
        self.assertEqual(r['physical_screen_point'],[-960,540])
    def test_reject_outside(self):
        with self.assertRaises(ValueError):s.map_point(str(self.image),1,.5)
    def test_no_invented_screen_origin(self):self.assertNotIn('physical_screen_point',s.map_point(str(self.image),.5,.5))
    def test_stale_tree_prevents_tap(self):
        old='<hierarchy><node text="A" bounds="[0,0][50,50]" clickable="true" /></hierarchy>'
        new=old.replace('text="A"','text="B"')
        state={'fingerprint':a._fingerprint(old)}
        calls=[]
        def adb(*args,**kw):
            calls.append(args)
            return (0,new if args[1]=='cat' else 'dumped')
        with patch.object(a,'_load',return_value=state):
            with self.assertRaisesRegex(ValueError,'UI changed'):a.click(adb,None,lambda:None,'unused',candidate_id=1)
        self.assertFalse(any('tap' in c for c in calls))
    def test_image_reference_idempotent(self):
        encoded=base64.b64encode(self.image.read_bytes()).decode()
        body={'input':[{'role':'user','content':[{'type':'input_image','image_url':'data:image/png;base64,'+encoded}]}]}
        gateway.normalize_media(body);gateway.normalize_media(body)
        content=body['input'][0]['content']
        self.assertEqual(len(content),2);self.assertIn('1080x2400',content[0]['text']);self.assertIn('normalized',content[0]['text'])

if __name__=='__main__':unittest.main(verbosity=2)
