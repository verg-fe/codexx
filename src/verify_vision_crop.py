import json,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
import vision_crop as v

class CropTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=r'G:\LocalCodex-work');self.root=Path(self.tmp.name)
        self.patch=patch.object(v,'JOBS',self.root);self.patch.start()
        self.source=self.root/'original.png';Image.new('RGBA',(1080,2400),(71,99,122,240)).save(self.source)
    def tearDown(self):self.patch.stop();self.tmp.cleanup()
    def prepared(self):return v.prepare(str(self.source),[590,1585,741,1820])
    def test_pixels_preserved_and_size_cropped(self):
        view=self.prepared()
        with Image.open(self.source) as a,Image.open(view['image_path']) as b:
            self.assertEqual(b.size,(151,235));self.assertEqual(a.crop(view['crop']).tobytes(),b.tobytes())
    def test_normalized_point_restores_original_target(self):
        view=self.prepared();self.assertEqual(v.map_view(view['view_id'],.5,.5)['image_point'],[665,1702])
    def test_resized_preview_point_restores_same_target(self):
        view=self.prepared();self.assertEqual(v.map_view(view['view_id'],75.5,117.5,151,235)['image_point'],[665,1702])
    def test_negative_monitor_origin(self):
        view=v.prepare(str(self.source),[0,0,1080,1200],[-3840,0,0,2160])
        self.assertEqual(v.map_view(view['view_id'],.5,.5)['physical_screen_point'],[-1920,540])
    def test_source_change_rejected(self):
        view=self.prepared();self.source.write_bytes(b'changed')
        with self.assertRaises(ValueError):v.map_view(view['view_id'],.5,.5)
    def test_expired_rejected(self):
        view=self.prepared();view['created_at']=time.time()-181
        (self.root/(view['view_id']+'-view.json')).write_text(json.dumps(view))
        with self.assertRaises(ValueError):v.map_view(view['view_id'],.5,.5)
    def test_invalid_crop_rejected(self):
        with self.assertRaises(ValueError):v.prepare(str(self.source),[0,0,1081,2400])
    def test_no_desktop_origin_invented(self):
        view=self.prepared();self.assertNotIn('physical_screen_point',v.map_view(view['view_id'],.5,.5))

if __name__=='__main__':unittest.main(verbosity=2)
