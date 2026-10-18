"""End-to-end diagnostic of the USB-install confirmation using CPU OCR only."""
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).parent))
import local_mcp_servers as local

work = Path(r'G:\LocalCodex-work\mycodex-repair-20261009\artifacts\android-mcp-test')
apk = work / 'huihui-apk-push-probe.apk'
package = 'com.mycodex.huihuipushprobe'
label = 'Huihui MCP Acceptance Probe'
pre = work / 'manual-confirm-before.png'
post = work / 'manual-confirm-after.png'
markers = ('USB安装提示', '通过USB安装', 'USB install', 'Install via USB')
buttons = ('继续安装', '继续', 'Continue install', 'Install anyway')


def capture_ocr():
    snap = local.android_coordinates.snapshot(local._adb, local._screenshot, local._require_device)
    state = local.android_coordinates._load(snap['snapshot_id'])
    result = local.android_coordinates.ocr(snap['snapshot_id'], '', 'contains', .35, 120)
    return snap, state, result


try:
    code, installed = local._adb('shell', 'pm', 'path', package)
    if code == 0 and 'package:' in installed:
        code, output = local._adb('uninstall', package, timeout=60)
        if code or 'Success' not in output:
            raise RuntimeError('Could not reset the dedicated acceptance package')
    code, install = local._adb('install', '-r', str(apk), timeout=120)
    if code or 'Success' not in install:
        raise RuntimeError(f'Install command failed: {install}')

    snap, state, ocr = capture_ocr()
    rows = ocr.get('matches', [])
    texts = [str(row.get('text') or '').strip() for row in rows]
    is_prompt = any(marker.casefold() in text.casefold() for marker in markers for text in texts)
    if not is_prompt:
        raise RuntimeError('Expected USB install dialog was not identified by OCR.')
    if texts.count(label) != 1:
        raise RuntimeError('USB install prompt did not show one exact acceptance-app label.')
    confirm_rows = [row for row in rows if str(row.get('text') or '').strip() in buttons
                    and row.get('bbox') and len(row['bbox']) == 4]
    if len(confirm_rows) != 1:
        raise RuntimeError(f'Expected one OCR confirmation box; got {len(confirm_rows)}')
    left, top, right, bottom = map(int, confirm_rows[0]['bbox'])
    point = local.android_coordinates.map_point(state['snapshot_id'], (left + right) / 2,
        (top + bottom) / 2, state['width'], state['height'])['device_point']
    pre.write_bytes(Path(state['screenshot_path']).read_bytes())
    method = 'adb-shell'
    try:
        result = local.android_coordinates.click(local._adb, local._screenshot, local._require_device,
            state['snapshot_id'], device_point=point)
    except RuntimeError as error:
        if 'INJECT_EVENTS' not in str(error):
            raise
        result = local.android_coordinates.click(local._adb, local._screenshot, local._require_device,
            state['snapshot_id'], device_point=point, use_root=True)
        method = 'root-su'
    post_state = local.android_coordinates._load(result['after']['snapshot_id'])
    post.write_bytes(Path(post_state['screenshot_path']).read_bytes())
    after_ocr = local.android_coordinates.ocr(result['after']['snapshot_id'], '', 'contains', .35, 120)
    after_texts = [str(row.get('text') or '').strip() for row in after_ocr.get('matches', [])]
    still_prompt = any(marker.casefold() in text.casefold() for marker in markers for text in after_texts)
    if still_prompt and label in after_texts:
        raise RuntimeError('Prompt remained after the OCR-mapped guarded tap.')
    code, path = local._adb('shell', 'pm', 'path', package)
    if code or 'package:' not in path:
        raise RuntimeError('Package manager did not report the test app installed after confirmation.')
    result = {'ok': True, 'dialog_seen': True, 'app_label_matched': True,
        'confirm_device_point': point, 'dialog_dismissed_after_tap': True, 'installed': True,
        'app_launched': False, 'confirmation_method': method,
        'ocr_engine': ocr.get('engine'), 'ocr_providers': ocr.get('providers'),
        'before_screenshot': str(pre), 'after_screenshot': str(post)}
finally:
    code, path = local._adb('shell', 'pm', 'path', package)
    if code == 0 and 'package:' in path:
        cleanup_code, cleanup = local._adb('uninstall', package, timeout=60)
        if cleanup_code or 'Success' not in cleanup:
            raise RuntimeError('Dedicated probe cleanup failed.')
print(json.dumps(result, ensure_ascii=False))
