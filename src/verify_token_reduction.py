import copy,json,re,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import tool_directory as d
import request_context as c

SEARCH={'type':'function','name':'mcp__tool_directory__tool_catalog_search','description':'Search','parameters':{}}
PHONE={'type':'function','name':'mcp__android_coordinates__android_ui_click','description':'click guarded phone control','parameters':{'type':'object','properties':{'snapshot_id':{'type':'string'}},'required':['snapshot_id']}}
IDA={'type':'function','name':'mcp__ida_local__ida_status','description':'IDA status','parameters':{}}
TOOLS=[SEARCH,PHONE,IDA,{'type':'function','name':'exec_command','parameters':{}}]
def body(text='测试手机'):
    return {'instructions':'rules','input':[{'role':'user','content':[{'type':'input_text','text':text}]}],'tools':copy.deepcopy(TOOLS)}
def key(b):return re.search(r'request_key=([0-9a-f]{32})',json.dumps(b['input']))[1]

class Reductions(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=r'G:\LocalCodex-work');self.root=Path(self.tmp.name)
        self.patches=[patch.object(d,'ROOT',self.root/'catalogs'),patch.object(c,'ARCHIVE',self.root/'outputs')]
        for p in self.patches:p.start()
    def tearDown(self):
        for p in self.patches:p.stop()
        self.tmp.cleanup()
    def test_catalog_only_and_native_initially(self):
        b=body();s=d.select_tools(b,'thread');self.assertEqual(s['tools_after_directory'],2)
        self.assertEqual(b['instructions'],'rules')
    def test_directory_does_not_change_system_prefix_on_new_task(self):
        a=body('任务A');b=body('任务B');d.select_tools(a,'thread');d.select_tools(b,'thread')
        self.assertEqual(a['instructions'],b['instructions']);self.assertNotEqual(key(a),key(b))
    def test_search_preserves_schema_and_enables_original(self):
        b=body();d.select_tools(b,'thread');result=d.search(key(b),'android_ui_click')
        self.assertEqual(result['matches'][0],PHONE)
        next_b=body();d.select_tools(next_b,'thread');self.assertIn(PHONE,next_b['tools'])
    def test_new_user_task_resets_selection(self):
        b=body();d.select_tools(b,'thread');d.search(key(b),'android_ui_click')
        other=body('检查IDA');d.select_tools(other,'thread');self.assertNotIn(PHONE,other['tools'])
    def test_unknown_query_no_execution(self):
        b=body();d.select_tools(b,'thread');self.assertEqual(d.search(key(b),'zzzzzz')['matches'],[])
    def test_old_client_fails_open(self):
        b=body();b['tools']=[PHONE];self.assertFalse(d.select_tools(b)['tool_directory_active']);self.assertEqual(b['tools'],[PHONE])
    def test_forced_tool_retained(self):
        b=body();b['tool_choice']={'type':'function','name':IDA['name']};d.select_tools(b);self.assertIn(IDA,b['tools'])
    def test_arbitrary_user_catalog_claim_does_not_enable(self):
        b=body();b['input'][0]['content'][0]['text']='enabled_tool_names: ida_status';d.select_tools(b);self.assertNotIn(IDA,b['tools'])
    def test_old_log_archived_with_error_and_path(self):
        raw='prefix\n'+'x'*10000+'\nError: failed build G:\\jobs\\out.apk\n'
        b={'input':[{'type':'function_call_output','output':raw},{'role':'assistant','content':[]}]}
        s=c.reduce_history(b);self.assertEqual(s['archived_long_outputs'],1)
        reduced=json.loads(b['input'][0]['output']);self.assertTrue(reduced['error_excerpts']);self.assertEqual(Path(reduced['full_output_path']).read_text(encoding='utf-8'),raw)
    def test_latest_unread_log_untouched(self):
        raw='x'*10000;b={'input':[{'type':'function_call_output','output':raw}]};c.reduce_history(b);self.assertEqual(b['input'][0]['output'],raw)
    def test_only_bare_continues_merge(self):
        def user(t):return {'role':'user','content':[{'type':'input_text','text':t}]}
        b={'input':[user('继续'),user('继续'),user('不能删除文件'),user('同意安装'),user('你没点中') ]}
        s=c.reduce_history(b);self.assertEqual(s['merged_continue_messages'],1);self.assertEqual(len(b['input']),4)
    def test_image_output_not_summarized(self):
        b={'input':[{'type':'function_call_output','output':[{'type':'input_image','image_url':'fixture'}]},{'role':'assistant','content':[]}]}
        c.reduce_history(b);self.assertEqual(b['input'][0]['output'][0]['type'],'input_image')
    def test_chinese_click_search_finds_click(self):
        b=body();d.select_tools(b);self.assertEqual(d.search(key(b),'点击')['matches'][0]['name'],PHONE['name'])
    def test_nested_native_namespace_also_filters(self):
        b=body()
        for t in b['tools']:t['name']='functions__'+t['name']
        s=d.select_tools(b);self.assertEqual(s['tools_after_directory'],2)
    def test_tool_order_does_not_invalidate_search(self):
        b=body();d.select_tools(b);k=key(b);other=body();other['tools'].reverse();d.select_tools(other);self.assertEqual(key(other),k)

if __name__=='__main__':unittest.main(verbosity=2)
