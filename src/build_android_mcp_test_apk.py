"""Build a harmless, no-launchable-activity APK for the authorized Android MCP acceptance test."""
from __future__ import annotations
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import zipfile

WORK=Path(r'G:\LocalCodex-work\mycodex-repair-20261009')
OUT=WORK/'artifacts'/'android-mcp-test'
SDK=Path(r'C:\Users\18213\AppData\Local\VectorAndroidSdk')
BUILD=sorted((SDK/'build-tools').glob('*'),reverse=True)[0]
PLATFORM=sorted((SDK/'platforms').glob('android-*'),reverse=True)[0]
JAVA=Path(r'C:\Program Files\Eclipse Adoptium\jdk-21.0.12.101-hotspot\bin')
PACKAGE='com.mycodex.huihuipushprobe'
PASSWORD=secrets.token_urlsafe(24)


def run(args, timeout=120):
    result=subprocess.run([str(item) for item in args],capture_output=True,text=True,
                          encoding='utf-8',errors='replace',timeout=timeout)
    if result.returncode:
        raise RuntimeError(f"{args[0]} exited {result.returncode}: {(result.stdout+result.stderr)[:2500]}")
    return result.stdout+result.stderr


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    work=OUT/'build-v1'
    if work.exists():
        raise FileExistsError(f'Preserving existing test fixture workspace: {work}')
    (work/'src'/'com'/'mycodex'/'huihuipushprobe').mkdir(parents=True)
    (work/'classes').mkdir()
    (work/'dex').mkdir()
    (work/'assets').mkdir()
    manifest=work/'AndroidManifest.xml'
    manifest.write_text(f'''<manifest xmlns:android="http://schemas.android.com/apk/res/android"
    package="{PACKAGE}" android:versionCode="1" android:versionName="1.0">
  <uses-sdk android:minSdkVersion="23" android:targetSdkVersion="28" />
  <application android:label="Huihui MCP Acceptance Probe" android:hasCode="true" />
</manifest>''',encoding='utf-8')
    java=work/'src'/'com'/'mycodex'/'huihuipushprobe'/'Probe.java'
    java.write_text(f'''package {PACKAGE};
public final class Probe {{
    private Probe() {{}}
    public static String identity() {{ return "{PACKAGE}"; }}
}}''',encoding='utf-8')
    payload=work/'assets'/'acceptance-only.bin'
    payload.write_bytes(bytes((index%251 for index in range(8192))))
    android_jar=PLATFORM/'android.jar'
    run([JAVA/'javac.exe','-source','8','-target','8','-classpath',android_jar,'-d',work/'classes',java])
    run(['cmd.exe','/d','/c',BUILD/'d8.bat','--min-api','23','--output',work/'dex',
         work/'classes'/'com'/'mycodex'/'huihuipushprobe'/'Probe.class'])
    unsigned=OUT/'probe-unsigned.apk'
    run([BUILD/'aapt.exe','package','-f','-M',manifest,'-A',work/'assets','-I',android_jar,'-F',unsigned])
    with zipfile.ZipFile(unsigned,'a',zipfile.ZIP_DEFLATED) as archive:
        archive.write(work/'dex'/'classes.dex','classes.dex')
    keystore=OUT/'test-signing-key.p12'
    run([JAVA/'keytool.exe','-genkeypair','-alias','huihui-test','-keyalg','RSA','-keysize','2048',
         '-validity','3650','-storetype','PKCS12','-keystore',keystore,
         '-storepass',PASSWORD,'-keypass',PASSWORD,'-dname','CN=Huihui Local Acceptance Test'])
    signer=BUILD/'apksigner.bat'
    signed=OUT/'huihui-apk-push-probe.apk'
    run(['cmd.exe','/d','/c',signer,'sign','--ks',keystore,'--ks-key-alias','huihui-test',
         '--ks-pass',f'pass:{PASSWORD}','--key-pass',f'pass:{PASSWORD}','--out',signed,unsigned])
    os.environ['ANDROID_SDK_ROOT']=str(SDK)
    sys.path.insert(0,str(Path(__file__).parent))
    from local_mcp_servers import _apk_metadata
    metadata=_apk_metadata(signed)
    if metadata['package_name']!=PACKAGE or not metadata['signature_verified'] or metadata['size_bytes']<4096:
        raise AssertionError(f'Generated APK failed preflight: {metadata}')
    result={'apk_path':str(signed),'package_name':PACKAGE,'version_code':metadata['version_code'],
            'min_sdk':metadata['min_sdk'],'native_abis':metadata['native_abis'],
            'certificate_sha256':metadata['certificate_sha256'],'sha256':__import__('hashlib').sha256(signed.read_bytes()).hexdigest(),
            'size_bytes':metadata['size_bytes'],'signature_verified':True,
            'has_launchable_activity':False,'purpose':'temporary isolated acceptance package'}
    (OUT/'probe-manifest.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':
    main()
