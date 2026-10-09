"""Packaged JSON-RPC acceptance for ScopeWeaver, VMware, and Android APK transfer/install."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

WORK=Path(r'G:\LocalCodex-work\mycodex-repair-20261009')
SOURCE=WORK/'source'
PACKAGED_EXE=Path(os.environ['LOCAL_CODEX_V61_EXE'])
os.environ['LOCAL_CODEX_SCOPEWEAVER_SOURCE_ROOT']=r'G:\LocalCodex-work\scopeweaver-review-20261009'
APK=Path(os.environ['LOCAL_CODEX_APK_FIXTURE'])
APK_CERT=os.environ['LOCAL_CODEX_APK_CERT_SHA256'].lower()
APK_NAME='Huihui-MCP-APK-push-test-v61.apk'
APK_PACKAGE='com.mycodex.huihuipushprobe'
SCREENSHOT=WORK/'artifacts'/'android-mcp-test'/'phone-after-install-v61.png'


def invoke(service, calls):
    requests=[{'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2024-11-05'}},
              {'jsonrpc':'2.0','id':2,'method':'tools/list','params':{}}]
    requests += [{'jsonrpc':'2.0','id':i+3,'method':'tools/call','params':{'name':name,'arguments':args}}
                 for i,(name,args) in enumerate(calls)]
    process=subprocess.Popen([str(PACKAGED_EXE),'--local-mcp-server',service],cwd=SOURCE,
        stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8',
        env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'})
    stdout,stderr=process.communicate(''.join(json.dumps(row,ensure_ascii=False)+'\n' for row in requests),timeout=120)
    if process.returncode:
        raise RuntimeError(f'{service} exited {process.returncode}: {stderr[:1200]}')
    replies={row['id']:row for row in (json.loads(line) for line in stdout.splitlines() if line.strip())}
    if len(replies)!=len(requests):
        raise AssertionError(f'{service} returned {len(replies)} of {len(requests)} JSON-RPC replies')
    if replies[1]['result'].get('serverInfo',{}).get('version')!='61.0':
        raise AssertionError(f'{service} server version is not v61: {replies[1]}')
    return replies


def exercise_readonly_services():
    scope=invoke('scopeweaver-source',[
        ('scopeweaver_source_info',{}),
        ('scopeweaver_search_source',{'query':'AGPL-3.0','limit':3}),
        ('scopeweaver_read_source',{'relative_path':'README.md','max_chars':400}),
        ('scopeweaver_read_source',{'relative_path':'../README.md'}),
    ])
    vmware=invoke('vmware',[('vmware_status',{}),('vmware_list_running_vms',{})])
    scope_calls=[scope[i]['result'] for i in range(3,7)]
    if any(item.get('isError') for item in scope_calls[:3]) or not scope_calls[3].get('isError'):
        raise AssertionError('ScopeWeaver source read or traversal guard failed.')
    if not scope_calls[0]['structuredContent'].get('history_preserved'):
        raise AssertionError('ScopeWeaver commit history metadata missing.')
    if any(vmware[i]['result'].get('isError') for i in (3,4)):
        raise AssertionError('VMware read-only JSON-RPC failed.')
    return {'scopeweaver':{'info':scope_calls[0]['structuredContent'],
            'search_hit_count':scope_calls[1]['structuredContent'].get('count'),
            'read_ok':True,'traversal_rejected':True},
        'vmware':{'status':vmware[3]['result']['structuredContent'],
                  'running_vm_count':vmware[4]['result']['structuredContent'].get('count')}}


def exercise_android():
    preflight=invoke('android',[('android_packages',{'prefix':APK_PACKAGE})])
    already=preflight[3]['result']['structuredContent'].get('third_party_packages',[])
    if APK_PACKAGE in already:
        raise RuntimeError('Acceptance probe package already exists on the phone; refusing to replace an unknown installation.')
    result=invoke('android',[
        ('android_apk_inspect',{'apk_path':str(APK)}),
        ('android_push_apk',{'apk_path':str(APK),'destination_name':'../bad.apk'}),
        ('android_push_apk',{'apk_path':str(APK),'destination_name':APK_NAME}),
        ('android_install_apks',{'apk_paths':[str(APK)],'package_name':APK_PACKAGE,
                                 'expected_certificate_sha256':'0'*64}),
        ('android_install_apks',{'apk_paths':[str(APK)],'package_name':APK_PACKAGE,
                                 'expected_certificate_sha256':APK_CERT}),
        ('android_screenshot',{'destination':str(SCREENSHOT)}),
        ('android_packages',{'prefix':APK_PACKAGE}),
    ])
    tools=result[2]['result']['tools']
    names={row['name'] for row in tools}
    if 'android_push_apk' not in names or 'android_install_apks' not in names:
        raise AssertionError('Packaged Android MCP is missing push/install tools.')
    inspect,push_bad,push,install_bad,install,screenshot,packages=[result[i]['result'] for i in range(3,10)]
    if inspect.get('isError') or not inspect['structuredContent'].get('signature_verified'):
        raise AssertionError('APK identity/signature preflight failed.')
    if not push_bad.get('isError'):
        raise AssertionError('Unsafe destination filename was not rejected.')
    pushed=push['structuredContent']
    if push.get('isError') or not pushed.get('pushed') or not pushed.get('remote_sha256_matches'):
        raise AssertionError('Packaged MCP push/hash verification failed: '+str(push))
    if pushed.get('installed') or pushed.get('launched'):
        raise AssertionError('Push-only operation unexpectedly installed or launched the APK.')
    if not install_bad.get('isError'):
        raise AssertionError('Wrong signing certificate was not rejected before install.')
    installed=install['structuredContent']
    if install.get('isError') or not installed.get('installed') or installed.get('launched'):
        raise AssertionError('Explicit install MCP failed or launched the app: '+str(install))
    confirmation=installed.get('usb_install_confirmation',{})
    if not confirmation.get('detected') or not confirmation.get('confirmed'):
        raise AssertionError('USB install dialog was not automatically confirmed: '+str(confirmation))
    prompt_path=Path(confirmation.get('prompt_screenshot',''))
    if not prompt_path.is_file() or not prompt_path.read_bytes().startswith(b'\x89PNG\r\n\x1a\n'):
        raise AssertionError('Pre-confirmation dialog screenshot is missing or invalid.')
    screenshot_path=Path(screenshot.get('structuredContent',{}).get('path',''))
    if screenshot.get('isError') or not screenshot_path.is_file() or not screenshot_path.read_bytes().startswith(b'\x89PNG\r\n\x1a\n'):
        raise AssertionError('Immediate post-install screenshot is missing or invalid.')
    found=packages['structuredContent'].get('third_party_packages',[])
    if packages.get('isError') or APK_PACKAGE not in found:
        raise AssertionError('Package manager cannot see the installed acceptance app.')
    import local_mcp_servers as local
    cleanup=subprocess.run([str(local.ADB),'-s',local.DEVICE,'uninstall',APK_PACKAGE],capture_output=True,
        timeout=60,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    cleanup_text=(cleanup.stdout+cleanup.stderr).decode('utf-8',errors='replace')
    if cleanup.returncode or 'Success' not in cleanup_text:
        raise RuntimeError('Verified temporary test install but could not remove the dedicated probe: '+cleanup_text[:400])
    post_cleanup=invoke('android',[('android_packages',{'prefix':APK_PACKAGE})])
    remaining=post_cleanup[3]['result']['structuredContent'].get('third_party_packages',[])
    if APK_PACKAGE in remaining:
        raise AssertionError('Temporary acceptance app still appears in the package manager after cleanup.')
    for call in (pushed,installed):
        call.pop('serial',None)
    return {'tool_names':sorted(names),'apk_inspection':inspect['structuredContent'],
            'unsafe_destination_rejected':True,'push':pushed,'wrong_certificate_rejected':True,
            'install':installed,'package_manager_verified':True,'installed_package':APK_PACKAGE,
            'app_launched':False,'temporary_probe_uninstalled':True,
            'pushed_apk_retained_on_phone':True,'install_prompt_auto_confirmed':True,
            'prompt_screenshot':str(prompt_path),'prompt_screenshot_bytes':prompt_path.stat().st_size,
            'post_install_screenshot':str(screenshot_path),'screenshot_bytes':screenshot_path.stat().st_size,
            'serial_redacted':True}


def main():
    if not APK.is_file():
        raise FileNotFoundError(APK)
    expected_sha=hashlib.sha256(APK.read_bytes()).hexdigest()
    readonly=exercise_readonly_services()
    android=exercise_android()
    evidence={'ok':True,'runtime':'packaged v61 exe','protocol':'JSON-RPC stdio initialize/tools-list/tools-call',
              'apk_fixture_sha256':expected_sha,'apk_certificate_sha256':APK_CERT,
              'android':android,**readonly}
    output=WORK/'artifacts'/'verify-v61-mcp-live.json'
    output.write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'ok':True,'evidence':str(output),'apk_sha256':expected_sha,
        'apk_pushed_and_remote_hash_verified':android['push']['remote_sha256_matches'],
        'apk_installed':android['install']['installed'],'apk_launched':False,
        'scopeweaver_traversal_rejected':readonly['scopeweaver']['traversal_rejected'],
        'vmware_read_only_calls_passed':True},ensure_ascii=False))


if __name__=='__main__':
    main()
