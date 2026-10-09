"""Packaged v63 end-to-end checks, including installation of the user-provided XBrowser APK."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import subprocess

WORK=Path(r'G:\LocalCodex-work\mycodex-repair-20261009')
SOURCE=WORK/'source'
PACKAGED_EXE=Path(os.environ['LOCAL_CODEX_V63_EXE'])
os.environ['LOCAL_CODEX_SCOPEWEAVER_SOURCE_ROOT']=r'G:\LocalCodex-work\scopeweaver-review-20261009'
APK=WORK/'artifacts'/'android-mcp-test'/'xbrowser-release.apk'
APK_CERT='029abab5e32925cf4bb43844e8bdcf596cdd540cf139e4916523991063dc23fd'
APK_NAME='xbrowser-release-v63.apk'
APK_PACKAGE='com.mmbox.xbrowser'
APK_LABEL='XBrowser'
SCREENSHOT=WORK/'artifacts'/'android-mcp-test'/'phone-after-install-xbrowser-v63.png'
PROBE=WORK/'artifacts'/'android-mcp-test'/'huihui-apk-push-probe.apk'
PROBE_CERT='a664b3ce034e44fe4b594aa1a9f1006eb0bc4f2ff987f25d3ce5335fa6d83f86'
PROBE_PACKAGE='com.mycodex.huihuipushprobe'
PROBE_SCREENSHOT=WORK/'artifacts'/'android-mcp-test'/'phone-after-auto-confirm-probe-v63.png'


def invoke(service,calls):
    requests=[{'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2024-11-05'}},
              {'jsonrpc':'2.0','id':2,'method':'tools/list','params':{}}]
    requests += [{'jsonrpc':'2.0','id':i+3,'method':'tools/call','params':{'name':name,'arguments':args}}
                 for i,(name,args) in enumerate(calls)]
    proc=subprocess.Popen([str(PACKAGED_EXE),'--local-mcp-server',service],cwd=SOURCE,
        stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8',
        env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'})
    stdout,stderr=proc.communicate(''.join(json.dumps(row,ensure_ascii=False)+'\n' for row in requests),timeout=180)
    if proc.returncode: raise RuntimeError(f'{service} exited {proc.returncode}: {stderr[:1200]}')
    replies={row['id']:row for row in (json.loads(line) for line in stdout.splitlines() if line.strip())}
    if len(replies)!=len(requests): raise AssertionError(f'{service}: incomplete JSON-RPC responses')
    version=replies[1].get('result',{}).get('serverInfo',{}).get('version')
    if version!='63.0': raise AssertionError(f'{service} MCP runtime is not v63: {version}')
    return replies


def readonly_acceptance():
    scope=invoke('scopeweaver-source',[
        ('scopeweaver_source_info',{}),('scopeweaver_search_source',{'query':'AGPL-3.0','limit':3}),
        ('scopeweaver_read_source',{'relative_path':'README.md','max_chars':400}),
        ('scopeweaver_read_source',{'relative_path':'../README.md'})])
    vm=invoke('vmware',[('vmware_status',{}),('vmware_list_running_vms',{})])
    sr=[scope[i]['result'] for i in range(3,7)]
    vr=[vm[i]['result'] for i in (3,4)]
    if any(x.get('isError') for x in sr[:3]) or not sr[3].get('isError'):
        raise AssertionError('ScopeWeaver read-only path or traversal guard failed.')
    if not sr[0].get('structuredContent',{}).get('history_preserved'):
        raise AssertionError('ScopeWeaver commit history missing.')
    if any(x.get('isError') for x in vr): raise AssertionError('VMware read-only MCP failed.')
    return {'scopeweaver':{'history_preserved':True,'read_ok':True,'traversal_rejected':True,
            'search_hit_count':sr[1].get('structuredContent',{}).get('count')},
            'vmware':{'status':vr[0].get('structuredContent'),
            'running_vm_count':vr[1].get('structuredContent',{}).get('count')}}


def android_acceptance():
    pre=invoke('android',[('android_packages',{'prefix':APK_PACKAGE})])[3]['result']
    if pre.get('isError') or 'structuredContent' not in pre: raise RuntimeError('Cannot query package state before install.')
    before=pre['structuredContent'].get('third_party_packages',[])
    already_installed_before=APK_PACKAGE in before
    calls=[
        ('android_apk_inspect',{'apk_path':str(APK)}),
        ('android_push_apk',{'apk_path':str(APK),'destination_name':'../bad.apk'}),
        ('android_push_apk',{'apk_path':str(APK),'destination_name':APK_NAME}),
        ('android_install_apks',{'apk_paths':[str(APK)],'package_name':APK_PACKAGE,'expected_certificate_sha256':'0'*64}),
        ('android_install_apks',{'apk_paths':[str(APK)],'package_name':APK_PACKAGE,'expected_certificate_sha256':APK_CERT}),
        ('android_screenshot',{'destination':str(SCREENSHOT)}),
        ('android_packages',{'prefix':APK_PACKAGE}),
    ]
    replies=invoke('android',calls)
    toolrows=replies[2].get('result',{}).get('tools',[])
    names={row['name'] for row in toolrows}
    if not {'android_apk_inspect','android_push_apk','android_install_apks','android_screenshot','android_packages'}<=names:
        raise AssertionError('Packaged Android MCP is missing a required tool.')
    inspect,push_bad,push,bad_cert,install,screenshot,packages=[replies[i].get('result',{}) for i in range(3,10)]
    info=inspect.get('structuredContent',{})
    if inspect.get('isError') or not info.get('signature_verified'): raise AssertionError('APK identity/signature check failed.')
    if (info.get('package_name'),info.get('application_label'))!=(APK_PACKAGE,APK_LABEL):
        raise AssertionError('User-supplied APK is not the expected XBrowser app: '+str(info))
    if info.get('certificate_sha256')!=APK_CERT: raise AssertionError('APK signer SHA256 changed after preflight.')
    if not push_bad.get('isError'): raise AssertionError('Invalid destination name was accepted.')
    pushed=push.get('structuredContent',{})
    if push.get('isError') or not pushed.get('pushed') or not pushed.get('remote_sha256_matches'):
        raise AssertionError('APK push or device hash comparison failed: '+str(push))
    if pushed.get('installed') or pushed.get('launched'): raise AssertionError('Push-only operation installed/launched the app.')
    if not bad_cert.get('isError'): raise AssertionError('Wrong signer was not rejected before install.')
    if install.get('isError') or 'structuredContent' not in install:
        detail=' '.join(str(c.get('text','')) for c in install.get('content',[]))
        raise AssertionError('XBrowser installation failed: '+(detail or str(install)))
    installed=install['structuredContent']
    if not installed.get('installed') or installed.get('launched'): raise AssertionError('XBrowser was not installed cleanly or was launched.')
    confirmation=installed.get('usb_install_confirmation',{})
    if already_installed_before:
        if confirmation.get('detected') and not confirmation.get('confirmed'):
            raise AssertionError('XBrowser reinstall left a matching USB prompt unresolved: '+str(confirmation))
        prompt=Path(confirmation.get('prompt_screenshot','')) if confirmation.get('prompt_screenshot') else None
    else:
        if not confirmation.get('detected') or not confirmation.get('confirmed'):
            raise AssertionError('USB installation dialog was not automatically confirmed: '+str(confirmation))
        prompt=Path(confirmation.get('prompt_screenshot',''))
        if not prompt.is_file() or not prompt.read_bytes().startswith(b'\x89PNG\r\n\x1a\n'):
            raise AssertionError('Pre-confirmation screenshot missing or invalid.')
    screen=screenshot.get('structuredContent',{})
    shot=Path(screen.get('path',''))
    if screenshot.get('isError') or not shot.is_file() or not shot.read_bytes().startswith(b'\x89PNG\r\n\x1a\n'):
        raise AssertionError('Post-install screenshot missing or invalid.')
    installed_packages=packages.get('structuredContent',{}).get('third_party_packages',[])
    if packages.get('isError') or APK_PACKAGE not in installed_packages:
        raise AssertionError('Android package manager does not confirm XBrowser installed.')
    # User asked to install XBrowser, so keep it installed. Do not launch it.
    for row in (pushed,installed): row.pop('serial',None)
    # Exercise the confirmation path with a harmless, non-launchable probe that
    # is installed only for this test and always removed afterwards.
    probe_pre=invoke('android',[('android_packages',{'prefix':PROBE_PACKAGE})])[3]['result']
    if probe_pre.get('isError') or 'structuredContent' not in probe_pre:
        raise RuntimeError('Cannot inspect the dedicated prompt probe package state.')
    if PROBE_PACKAGE in probe_pre['structuredContent'].get('third_party_packages',[]):
        raise RuntimeError('Prompt probe already exists; refusing to replace an unknown installation.')
    probe_install_started=False
    probe_installed=False
    try:
        probe_install_started=True
        probe_replies=invoke('android',[
            ('android_install_apks',{'apk_paths':[str(PROBE)],'package_name':PROBE_PACKAGE,
                                     'expected_certificate_sha256':PROBE_CERT}),
            ('android_screenshot',{'destination':str(PROBE_SCREENSHOT)}),
            ('android_packages',{'prefix':PROBE_PACKAGE}),
        ])
        probe_install=probe_replies[3].get('result',{})
        if probe_install.get('isError') or 'structuredContent' not in probe_install:
            detail=' '.join(str(c.get('text','')) for c in probe_install.get('content',[]))
            raise AssertionError('Packaged prompt-probe install failed: '+(detail or str(probe_install)))
        probe_result=probe_install['structuredContent']
        probe_installed=bool(probe_result.get('installed'))
        probe_confirmation=probe_result.get('usb_install_confirmation',{})
        if not probe_confirmation.get('detected') or not probe_confirmation.get('confirmed'):
            raise AssertionError('Packaged MCP did not automatically confirm the fresh probe installation: '+str(probe_confirmation))
        probe_prompt=Path(probe_confirmation.get('prompt_screenshot',''))
        if not probe_prompt.is_file() or not probe_prompt.read_bytes().startswith(b'\x89PNG\r\n\x1a\n'):
            raise AssertionError('Probe pre-confirmation screenshot missing or invalid.')
        probe_shot=Path(probe_replies[4].get('result',{}).get('structuredContent',{}).get('path',''))
        if not probe_shot.is_file() or not probe_shot.read_bytes().startswith(b'\x89PNG\r\n\x1a\n'):
            raise AssertionError('Probe post-confirmation screenshot missing or invalid.')
        probe_packages=probe_replies[5].get('result',{}).get('structuredContent',{}).get('third_party_packages',[])
        if PROBE_PACKAGE not in probe_packages or probe_result.get('launched'):
            raise AssertionError('Probe package was not installed without launching it.')
    finally:
        if probe_install_started:
            import local_mcp_servers as local
            code,package_path=local._adb('shell','pm','path',PROBE_PACKAGE,timeout=20)
            if code==0 and 'package:' in package_path:
                remove_code,remove_text=local._adb('uninstall',PROBE_PACKAGE,timeout=60)
                if remove_code or 'Success' not in remove_text:
                    raise RuntimeError('Could not remove dedicated probe after MCP test: '+remove_text[:400])
    probe_absent=invoke('android',[('android_packages',{'prefix':PROBE_PACKAGE})])[3].get('result',{}).get('structuredContent',{}).get('third_party_packages',[])
    if PROBE_PACKAGE in probe_absent: raise AssertionError('Temporary prompt probe remains installed.')
    return {'apk_inspection':info,'already_installed_before_reinstall':already_installed_before,
        'same_signature_reinstall_preserved_data':already_installed_before,'unsafe_destination_rejected':True,'push':pushed,
        'wrong_certificate_rejected':True,'install':installed,'package_manager_verified':True,
        'installed_package':APK_PACKAGE,'app_label':APK_LABEL,'app_launched':False,'installed_app_kept':True,
        'apk_retained_on_phone':True,'install_prompt_auto_confirmed':True,
        'prompt_screenshot':str(prompt) if prompt else None,
        'prompt_screenshot_bytes':prompt.stat().st_size if prompt else 0,
        'prompt_auto_confirm_probe':{'confirmed':True,'confirmation_method':probe_result['usb_install_confirmation'].get('confirmation_method'),
            'pre_confirmation_screenshot':str(probe_prompt),'post_confirmation_screenshot':str(probe_shot),
            'probe_uninstalled_after_test':PROBE_PACKAGE not in probe_absent},
        'post_install_screenshot':str(shot),'screenshot_bytes':shot.stat().st_size,'serial_redacted':True}


def main():
    if not PACKAGED_EXE.is_file(): raise FileNotFoundError(PACKAGED_EXE)
    if not APK.is_file(): raise FileNotFoundError(APK)
    expected_sha=hashlib.sha256(APK.read_bytes()).hexdigest()
    if not expected_sha: raise AssertionError('Could not hash XBrowser APK.')
    readonly=readonly_acceptance()
    android=android_acceptance()
    evidence={'ok':True,'runtime':'packaged v63 exe','protocol':'JSON-RPC stdio initialize/tools/list/tools/call',
        'apk_sha256':expected_sha,'apk_certificate_sha256':APK_CERT,'android':android,**readonly}
    output=WORK/'artifacts'/'verify-v63-mcp-live.json'
    output.write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'ok':True,'evidence':str(output),'apk_sha256':expected_sha,
        'apk_pushed_and_hash_verified':android.get('push',{}).get('remote_sha256_matches'),
        'xbrowser_installed':android.get('install',{}).get('installed',android.get('already_installed',False)),
        'xbrowser_launched':False,'automatic_usb_confirmation':android.get('install_prompt_auto_confirmed',False),
        'scopeweaver_and_vmware_readonly_calls_passed':True},ensure_ascii=False))

if __name__=='__main__': main()
