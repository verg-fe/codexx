import unittest
from vision_history import archive_observed_tool_images

def call(name='mcp__android__android_screenshot',arguments='{"destination":"G:/LocalCodex/android-ui-jobs/current.png"}'):
    return {'type':'function_call','call_id':'ui1','name':name,'arguments':arguments}
def output():return {'type':'function_call_output','call_id':'ui1','output':[{'type':'input_image','image_url':'data:image/png;base64,fixture'}]}

class StaleUIImages(unittest.TestCase):
    def test_pending_old_ui_before_continue_is_removed(self):
        body={'input':[call(),output(),{'role':'user','content':[{'type':'input_text','text':'继续'}]}]}
        stats=archive_observed_tool_images(body)
        self.assertEqual(stats['stale_tool_images'],1);self.assertEqual(stats['pending_tool_images'],0)
        self.assertEqual(body['input'][1]['output'][0]['type'],'input_text')
    def test_fresh_tool_image_after_instruction_is_retained(self):
        body={'input':[{'role':'user','content':[]},call(),output()]}
        stats=archive_observed_tool_images(body)
        self.assertEqual(stats['pending_tool_images'],1);self.assertEqual(stats['stale_tool_images'],0)
    def test_user_photo_is_retained(self):
        body={'input':[{'role':'user','content':[{'type':'input_image','image_url':'photo'}]},{'role':'user','content':[]}]}
        stats=archive_observed_tool_images(body)
        self.assertEqual(stats['user_images'],1);self.assertEqual(body['input'][0]['content'][0]['type'],'input_image')
    def test_static_unobserved_photo_is_retained(self):
        body={'input':[call('view_image','{"path":"G:/LocalCodex/image-jobs/photo.png"}'),output(),{'role':'user','content':[]}]}
        stats=archive_observed_tool_images(body)
        self.assertEqual(stats['pending_tool_images'],1)
    def test_observed_placeholder_stays_stable(self):
        body={'input':[call(),output(),{'role':'assistant','content':[]},{'role':'user','content':[]}]}
        stats=archive_observed_tool_images(body)
        self.assertEqual(stats['archived_tool_images'],1);self.assertEqual(stats['stale_tool_images'],0)
        self.assertTrue(body['input'][1]['output'][0]['text'].startswith('[Previously observed tool screenshot.'))

if __name__=='__main__':unittest.main(verbosity=2)
