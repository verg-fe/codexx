"""Focused checks for connection fallback, G-drive sessions, and turn-scoped skills."""
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import call, patch

import core
from proxy_service import PROXY_KEYS, ProxyLease
_bs4=types.ModuleType('bs4')
_bs4.BeautifulSoup=lambda *args,**kwargs: None
sys.modules.setdefault('bs4',_bs4)
from web_tools import NetworkTools


class FollowupRepairChecks(unittest.TestCase):
    def test_failed_proxy_does_not_block_local_engine_and_fails_closed_for_web(self):
        lease=ProxyLease.__new__(ProxyLease)
        lease.enabled=True
        lease.process=None
        env={key:'http://unrelated-system-proxy' for key in PROXY_KEYS}
        lease.apply_environment(env,allow_unavailable=True)
        self.assertEqual(env['LOCAL_CODEX_PROXY_URL'],'unavailable')
        self.assertFalse(any(key in env for key in PROXY_KEYS))
        with self.assertRaisesRegex(RuntimeError,'避免绕过代理'):
            NetworkTools('unavailable').fetch('https://example.com')

    def test_skill_index_only_lists_relevant_configured_mcp_servers(self):
        with tempfile.TemporaryDirectory() as temp:
            home=Path(temp)/'codex-home';home.mkdir()
            (home/'config.toml').write_text('''
[model_providers.private]
experimental_bearer_token = "DO_NOT_EXPOSE"
[mcp_servers.shotcut]
command = "python"
[mcp_servers.local_history]
command = "python"
''',encoding='utf-8')
            text=core.mcp_skill_index('帮我剪辑这个视频',root=temp)
            self.assertIn('shotcut',text)
            self.assertNotIn('local_history',text)
            self.assertNotIn('DO_NOT_EXPOSE',text)
            self.assertNotIn('web_research',text)

    def test_unrelated_instruction_gets_a_minimal_skill_index(self):
        with tempfile.TemporaryDirectory() as temp:
            home=Path(temp)/'codex-home';home.mkdir()
            (home/'config.toml').write_text('''[mcp_servers.shotcut]
command = "python"
[mcp_servers.photoslop]
command = "python"
[mcp_servers.android]
command = "python"
''',encoding='utf-8')
            text=core.mcp_skill_index('请解释二次函数',root=temp)
            self.assertNotIn('shotcut',text)
            self.assertNotIn('photoslop',text)
            self.assertNotIn('android',text)
            self.assertLess(len(text),50)

    def test_mobile_reasoning_choice_is_reused_by_followup_turns(self):
        app_source=(Path(__file__).parent/'app.py').read_text(encoding='utf-8')
        mobile_source=(Path(__file__).parent/'mobile_upload.py').read_text(encoding='utf-8')
        page_source=(Path(__file__).parent/'mobile-app'/'index.html').read_text(encoding='utf-8')
        self.assertIn("self.mobile_reasoning_effort=normalize_reasoning_effort(job.get('reasoning_effort'))",app_source)
        self.assertGreaterEqual(app_source.count('_effort_for_active_turn()'),2)
        self.assertIn("reasoning_effort:$('reasoningEffort').value",page_source)
        self.assertIn("'reasoning_effort':reasoning_effort",mobile_source)

    def test_prepare_moves_new_session_root_off_c_when_configured(self):
        with tempfile.TemporaryDirectory() as temp, \
             patch.object(core,'ROOT',Path(temp)), \
             patch.dict(os.environ,{'LOCAL_CODEX_ROOT':temp}):
            settings={'api_key':'test-only','model':core.MODEL,
                      'session_workspace_root':r'C:\my_projects\CodexSessions'}
            prepared=core.prepare(settings)
            self.assertEqual(prepared['session_workspace_root'],r'G:\LocalCodex\CodexSessions')
            self.assertTrue((Path(temp)/'codex-home'/'config.toml').is_file())
            self.assertIn('mcp_servers', (Path(temp)/'codex-home'/'config.toml').read_text(encoding='utf-8'))
            import tomllib
            servers=tomllib.loads((Path(temp)/'codex-home'/'config.toml').read_text(encoding='utf-8')).get('mcp_servers',{})
            self.assertIn('scopeweaver_source',servers)
            self.assertNotIn('artex_source',servers)
            self.assertIn('vmware',servers)
            text=(Path(temp)/'codex-home'/'config.toml').read_text(encoding='utf-8')
            self.assertNotIn('[mcp_servers.android.tools.android_install_apks]',text)
            self.assertIn('[mcp_servers.android.tools.android_launch]\napproval_mode = "approve"',text)
            self.assertNotIn('[mcp_servers.android.tools.android_push_apk]',text)
            import json
            catalog=json.loads((Path(temp)/'codex-model-catalog.json').read_text(encoding='utf-8'))
            self.assertFalse(catalog['models'][0]['include_skills_usage_instructions'])

    def test_skill_prompt_is_compact_and_task_scoped(self):
        self.assertNotIn('D:/LocalCodex/codex-home/skills/',core.INSTRUCTIONS)
        self.assertLess(len(core.LEARNING_INSTRUCTIONS),500)
        self.assertLess(len(core.INSTRUCTIONS),8500)

    def test_media_mcp_contracts_point_to_g_and_explain_required_inputs(self):
        source=Path(__file__).parent
        core_text=(source/'core.py').read_text(encoding='utf-8')
        photo_text=(source/'photoslop_huihui_mcp.py').read_text(encoding='utf-8')
        shotcut_text=(source/'shotcut_huihui_mcp.py').read_text(encoding='utf-8')
        windows_text=(source/'windows_mcp_integration.py').read_text(encoding='utf-8')
        desktop_skill=(source/'skills'/'windows-desktop-control'/'SKILL.md').read_text(encoding='utf-8')
        self.assertIn(r"G:\LocalCodex\tools\photoslop_huihui_mcp.py",core_text)
        self.assertIn(r"G:\LocalCodex\tools\shotcut_huihui_mcp.py",core_text)
        self.assertIn(r"G:\LocalCodex\image-jobs",photo_text)
        self.assertIn("暂存",photo_text)
        self.assertIn("以 .mp4 结尾",shotcut_text)
        self.assertIn("window_name",core_text)
        self.assertIn("window_name",windows_text)
        self.assertIn("window_name",desktop_skill)

    def test_scopeweaver_source_mcp_is_read_only_and_rejects_escape_paths(self):
        import local_mcp_servers as local
        names={row[0] for row in local._schemas()['scopeweaver-source']}
        self.assertEqual(names,{'scopeweaver_source_info','scopeweaver_search_source','scopeweaver_read_source'})
        info=local._scopeweaver_source_info()
        self.assertEqual(info['repository'],'cskwork/scopeweaver')
        self.assertEqual(info['upstream_base_commit'],'160fe13')
        self.assertTrue(info['history_preserved'],info)
        self.assertGreater(info['commit_count'],100,info)
        self.assertEqual(info['license'],'AGPL-3.0')
        self.assertEqual(info['commit'],'75a706d3146f9537ebf2cabe00ca540b6b033a85')
        self.assertFalse(info['runtime_installed'])
        self.assertIn('不扫描',info['scope'])
        self.assertNotIn('\ufffd',info['scope'])
        hit=local._scopeweaver_search_source('AGPL',5)
        self.assertTrue(hit['hits'])
        read=local._scopeweaver_read_source('README.md',500)
        self.assertIn('ScopeWeaver',read['text'])
        for value in ('../README.md',r'C:\Windows\win.ini','.env.example','.git/config'):
            with self.subTest(path=value), self.assertRaises(ValueError):
                local._scopeweaver_read_source(value)

    def test_scopeweaver_skill_is_available_from_the_g_drive_app_bundle(self):
        from skill_memory import SkillMemory
        with tempfile.TemporaryDirectory() as temp:
            store=SkillMemory(temp)
            found=store.search('ScopeWeaver 源码审查',10)['skills']
            row=next(item for item in found if item['name']=='scopeweaver-source-review')
            self.assertTrue(row['path'].startswith(str(Path(__file__).parent/'skills')))
            skill=store.read('scopeweaver-source-review')
            self.assertIn('read-only',skill['body'])
            self.assertIn('read-only',skill['description'])

    def test_scopeweaver_skill_index_is_only_sent_for_scopeweaver_requests(self):
        with tempfile.TemporaryDirectory() as temp:
            home=Path(temp)/'codex-home';home.mkdir()
            (home/'config.toml').write_text('[mcp_servers.scopeweaver_source]\ncommand="python"\n',encoding='utf-8')
            self.assertIn('scopeweaver_source',core.mcp_skill_index('请审查 ScopeWeaver 源码',root=temp))
            self.assertNotIn('scopeweaver_source',core.mcp_skill_index('解释二次函数',root=temp))

    def test_android_push_apk_copies_verified_g_drive_file_without_installing(self):
        import hashlib
        import local_mcp_servers as local
        apk=Path(r'G:\LocalCodex-work\mycodex-repair-20261009\artifacts\mcp-acceptance\out\apk-probe.apk')
        digest=hashlib.sha256(apk.read_bytes()).hexdigest()
        with patch.object(local,'_require_device',return_value=local.DEVICE), \
             patch.object(local,'_apk_metadata',return_value={'package_name':'com.android.deskclock','version_code':1303001500,'certificate_sha256':'c9009d01ebf9f5d0302bc71b2fe9aa9a47a432bba17308a3111b75d7b2149025'}), \
             patch.object(local,'_device_info',return_value={'properties':{'ro.product.model':'test-phone'}}), \
             patch.object(local,'_adb',side_effect=[(0,''),(0,'1 file pushed'),(0,digest+'  /sdcard/Download/test.apk')]) as adb:
            result=local._push_apk(str(apk),'Huihui-MCP-APK-push-test.apk')
        self.assertTrue(result['pushed'])
        self.assertFalse(result['installed'])
        self.assertFalse(result['launched'])
        self.assertTrue(result['remote_sha256_matches'])
        self.assertEqual(result['device_model'],'test-phone')
        adb.assert_any_call('push',str(apk),'/sdcard/Download/Huihui-MCP-APK-push-test.apk',timeout=300)
        with patch.object(local,'_adb') as never_called:
            with self.assertRaisesRegex(ValueError,'目标文件名'):
                local._push_apk(str(apk),'../bad.apk')
            never_called.assert_not_called()

    def test_android_usb_install_prompt_only_confirms_matching_apk_and_button(self):
        import local_mcp_servers as local
        prompt={'matches':[{'text':'USB安装提示'},{'text':'Huihui MCP Acceptance Probe'},
            {'text':'继续安装','bbox':[100,200,500,300]}]}
        home={'matches':[{'text':'桌面'}]}
        snap={'snapshot_id':'snap','screenshot_path':r'G:\snap.png'}
        after={'snapshot_id':'after','screenshot_path':r'G:\after.png'}
        with (patch.object(local.android_coordinates,'snapshot',side_effect=[snap,after]),
              patch.object(local.android_coordinates,'_load',return_value={'snapshot_id':'snap','width':1080,'height':2400}),
              patch.object(local.android_coordinates,'ocr',side_effect=[prompt,home]),
              patch.object(local.android_coordinates,'map_point',return_value={'device_point':[300,250]}),
              patch.object(local.android_coordinates,'click',return_value={'after':after}) as click,
              patch.object(local,'_capture_install_prompt_screenshot',return_value=r'G:\capture.png')):
            result=local._auto_confirm_usb_install('com.mycodex.huihuipushprobe','Huihui MCP Acceptance Probe')
        self.assertTrue(result['detected'])
        self.assertTrue(result['confirmed'])
        self.assertEqual(result['screen_coordinate'],[300,250])
        self.assertEqual(click.call_args.kwargs['device_point'],[300,250])

    def test_android_usb_install_prompt_accepts_only_manifest_localized_label(self):
        import local_mcp_servers as local
        prompt={'matches':[{'text':'USB安装提示'},{'text':'X浏览器'},
            {'text':'继续安装','bbox':[100,200,500,300]}]}
        home={'matches':[{'text':'桌面'}]}
        snap={'snapshot_id':'snap','screenshot_path':r'G:\snap.png'}
        after={'snapshot_id':'after','screenshot_path':r'G:\after.png'}
        with (patch.object(local.android_coordinates,'snapshot',side_effect=[snap,after]),
              patch.object(local.android_coordinates,'_load',return_value={'snapshot_id':'snap','width':1080,'height':2400}),
              patch.object(local.android_coordinates,'ocr',side_effect=[prompt,home]),
              patch.object(local.android_coordinates,'map_point',return_value={'device_point':[300,250]}),
              patch.object(local.android_coordinates,'click',return_value={'after':after}) as click,
              patch.object(local,'_capture_install_prompt_screenshot',return_value=r'G:\capture.png')):
            result=local._auto_confirm_usb_install('com.mmbox.xbrowser',['XBrowser','X浏览器'])
        self.assertTrue(result['confirmed'])
        self.assertEqual(result['matched_manifest_label'],'X浏览器')
        self.assertEqual(click.call_args.kwargs['device_point'],[300,250])

    def test_android_usb_install_prompt_with_different_package_label_is_never_clicked(self):
        import local_mcp_servers as local
        prompt={'matches':[{'text':'USB安装提示'},{'text':'Other application'},
            {'text':'继续安装','bbox':[100,200,500,300]}]}
        snap={'snapshot_id':'snap','screenshot_path':r'G:\snap.png'}
        with (patch.object(local.android_coordinates,'snapshot',return_value=snap),
              patch.object(local.android_coordinates,'_load',return_value={'snapshot_id':'snap','width':1080,'height':2400}),
              patch.object(local.android_coordinates,'ocr',return_value=prompt),
              patch.object(local.android_coordinates,'map_point') as map_point,
              patch.object(local.android_coordinates,'click') as click,
              patch.object(local,'_capture_install_prompt_screenshot') as capture):
            with self.assertRaisesRegex(RuntimeError,'未显示待安装 APK'):
                local._auto_confirm_usb_install('com.mycodex.huihuipushprobe','Huihui MCP Acceptance Probe')
            capture.assert_not_called()
            map_point.assert_not_called()
            click.assert_not_called()

    def test_android_usb_install_prompt_falls_back_to_existing_root_only_for_injection_denial(self):
        import local_mcp_servers as local
        prompt={'matches':[{'text':'USB安装提示'},{'text':'Huihui MCP Acceptance Probe'},
            {'text':'继续安装','bbox':[100,200,500,300]}]}
        home={'matches':[{'text':'桌面'}]}
        snap={'snapshot_id':'snap','screenshot_path':r'G:\snap.png'}
        after={'snapshot_id':'after','screenshot_path':r'G:\after.png'}
        with (patch.object(local.android_coordinates,'snapshot',side_effect=[snap,after]),
              patch.object(local.android_coordinates,'_load',return_value={'snapshot_id':'snap','width':1080,'height':2400}),
              patch.object(local.android_coordinates,'ocr',side_effect=[prompt,home]),
              patch.object(local.android_coordinates,'map_point',return_value={'device_point':[300,250]}),
              patch.object(local.android_coordinates,'click',side_effect=[RuntimeError('Tap command failed: INJECT_EVENTS denied'),{'after':after}]) as click,
              patch.object(local,'_capture_install_prompt_screenshot',return_value=r'G:\capture.png')):
            result=local._auto_confirm_usb_install('com.mycodex.huihuipushprobe','Huihui MCP Acceptance Probe')
        self.assertTrue(result['confirmed'])
        self.assertEqual(result['confirmation_method'],'root-su')
        self.assertEqual(click.call_count,2)
        self.assertTrue(click.call_args.kwargs['use_root'])

    def test_model_args_enable_prompt_cache_and_store_it_on_g(self):
        import core
        from pathlib import Path
        source=Path(__file__).parent
        cache=Path(r'G:\LocalCodex-work\mycodex-repair-20261009\tmp\prompt-cache-test')
        with patch.object(core,'PROMPT_CACHE_DIRECTORY',cache), \
             patch.object(core,'runtime_executable',return_value=Path(r'G:\runtime\llama-server.exe')), \
             patch.object(core,'model_file',return_value=Path(r'G:\models\test.gguf')), \
             patch.object(core,'model_supports_vision',return_value=False), \
             patch.object(core,'gpu_layers',return_value='all'), \
             patch.object(core,'kv_cache_location',return_value='gpu'):
            args=core.model_args(core.HUIHUI_IQ3S_MODEL,93000,settings={'api_key':'test','kv_cache_type':'q4_0','reasoning_effort':'xhigh','cpu_offload':False})
        self.assertIn('--cache-ram',args)
        self.assertEqual(args[args.index('--cache-ram')+1],'8192')
        self.assertIn('--cache-prompt',args)
        self.assertIn('--cache-idle-slots',args)
        self.assertNotIn('--no-cache-idle-slots',args)
        self.assertIn(str(cache),args[args.index('--slot-save-path')+1])
        self.assertTrue(cache.is_dir())

    def test_old_model_record_without_prompt_cache_forces_reload(self):
        cache=Path(r'G:\LocalCodex-work\mycodex-repair-20261009\tmp\prompt-cache-policy-test')
        with patch.object(core,'PROMPT_CACHE_DIRECTORY',cache):
            self.assertFalse(core.prompt_cache_policy_matches({'pid':14728}))
            self.assertTrue(core.prompt_cache_policy_matches({
                'prompt_cache_enabled':True,
                'prompt_cache_ram_mib':core.PROMPT_CACHE_RAM_MIB,
                'prompt_cache_idle_slots':True,
                'prompt_cache_directory':str(cache),
            }))
            self.assertFalse(core.prompt_cache_policy_matches({
                'prompt_cache_enabled':False,
                'prompt_cache_ram_mib':core.PROMPT_CACHE_RAM_MIB,
                'prompt_cache_idle_slots':True,
                'prompt_cache_directory':str(cache),
            }))


    def test_vmware_mcp_is_configured_and_reports_actual_read_only_state(self):
        import local_mcp_servers as local
        self.assertIn('vmware',local._schemas())
        status=local._vmware_status()
        self.assertTrue(status.get('installed'),status)
        self.assertGreater(status.get('vmware_size_bytes',0),0,status)
        self.assertNotIn('error',status)
        running=local._vmware_list_running_vms()
        self.assertEqual(running['exit_code'],0,running)
        self.assertGreaterEqual(running['count'],0,running)
        self.assertTrue(running['read_only'])


if __name__=='__main__':
    unittest.main(verbosity=2)
