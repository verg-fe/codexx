import copy,unittest
from request_context import MARKER,prune_reference_tails

def item(prompt='继续'):
    return {'role':'user','content':[{'type':'input_text','text':prompt+MARKER+'Local history archive thread_id: 01a117c9-8204-7352-8fde-2e7cf0cdf006\nApplication session directory: G:/jobs\n本轮技能索引：android'}]}

class ReferenceTests(unittest.TestCase):
    def test_preserves_user_request_and_latest_reference(self):
        body={'input':[item('不要删除数据'),item('继续')]};last=copy.deepcopy(body['input'][1])
        stats=prune_reference_tails(body)
        self.assertEqual(stats['historical_reference_blocks_removed'],1)
        self.assertEqual(body['input'][0]['content'][0]['text'],'不要删除数据')
        self.assertEqual(body['input'][1],last)
    def test_keeps_reference_before_steer(self):
        body={'input':[item(),item(),{'role':'user','content':[{'type':'input_text','text':'先别点击'}]}]}
        prune_reference_tails(body);self.assertIn(MARKER,body['input'][1]['content'][0]['text'])
    def test_keeps_images(self):
        body={'input':[item(),item()]};body['input'][0]['content'].append({'type':'input_image','image_url':'fixture'})
        prune_reference_tails(body);self.assertEqual(body['input'][0]['content'][1]['type'],'input_image')
    def test_marker_alone_not_removed(self):
        body={'input':[{'role':'user','content':[{'type':'input_text','text':'讨论这个标记'+MARKER+'未知内容'}]},item()]}
        before=copy.deepcopy(body['input'][0]);prune_reference_tails(body);self.assertEqual(body['input'][0],before)
    def test_developer_summary_unchanged(self):
        summary=item();summary['role']='developer';body={'input':[summary,item()]}
        before=copy.deepcopy(summary);prune_reference_tails(body);self.assertEqual(summary,before)
    def test_repeat_is_idempotent(self):
        body={'input':[item(),item()]};prune_reference_tails(body)
        self.assertEqual(prune_reference_tails(body)['historical_reference_blocks_removed'],0)

if __name__=='__main__':unittest.main(verbosity=2)
