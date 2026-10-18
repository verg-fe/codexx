"""Recreate the isolated install prompt and save screenshot/OCR evidence on G:."""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent))
import local_mcp_servers as local

work = Path(r'G:\LocalCodex-work\mycodex-repair-20261009\artifacts\android-mcp-test')
apk = work / 'huihui-apk-push-probe.apk'
package = 'com.mycodex.huihuipushprobe'
code, path = local._adb('shell', 'pm', 'path', package)
if code == 0 and 'package:' in path:
    uninstall_code, uninstall = local._adb('uninstall', package, timeout=60)
    if uninstall_code or 'Success' not in uninstall:
        raise RuntimeError('Unable to remove only the prior dedicated acceptance probe: ' + uninstall)
code, install = local._adb('install', '-r', str(apk), timeout=120)
snapshot = local.android_coordinates.snapshot(local._adb, local._screenshot, local._require_device)
state = local.android_coordinates._load(snapshot['snapshot_id'])
ocr = local.android_coordinates.ocr(snapshot['snapshot_id'], '', 'contains', .35, 120)
image = work / 'install-prompt-probe.png'
image.write_bytes(Path(state['screenshot_path']).read_bytes())
report = {
    'adb_install_exit_code': code,
    'adb_install_output': install,
    'ocr_engine': ocr.get('engine'),
    'ocr_providers': ocr.get('providers'),
    'image_size': ocr.get('image_size'),
    'recognized_text': ocr.get('matches', []),
    'screenshot': str(image),
    'snapshot_id': snapshot['snapshot_id'],
}
(work / 'install-prompt-probe.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({'adb_install_exit_code': code, 'adb_install_output': install,
    'recognized_text': [row.get('text') for row in report['recognized_text']]}, ensure_ascii=False))
