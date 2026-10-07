"""Install v36 alongside v35 and update the reversible desktop launcher."""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil

WORKSPACE = Path(__file__).resolve().parent
SOURCE = WORKSPACE / 'release36'
ROOT = Path(r'D:\LocalCodex')
BACKUP = Path(r'C:\my_projects\MyCodex-v35-backup-20261007-104748')
STAGE = ROOT / 'staging' / 'proxy-model36-ready' / 'MyCodex'
INSTALL = ROOT / 'app' / 'MyCodex-proxy36'
OLD = ROOT / 'app' / 'MyCodex-moe35-final' / 'MyCodex.exe'
SHORTCUT = Path(r'C:\Users\18213\Desktop\我的Codex.cmd')
ROLLOUT = ROOT / 'codex-home' / 'sessions' / '2026' / '10' / '07' / 'rollout-2026-10-07T10-01-46-01a11418-69c6-7ae2-8779-3913a2b2bb97.jsonl'


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def inspect_latest_log():
    calls = Counter()
    stats = {'custom_tool_calls': 0, 'compactions': 0, 'zero_exit_property_exceptions': 0,
        'printed_tool_calls': 0, 'constructor_errors': 0, 'rows': 0}
    for line in ROLLOUT.open(encoding='utf-8'):
        try:
            event = json.loads(line)
        except ValueError:
            continue
        stats['rows'] += 1
        stats['last_timestamp'] = event.get('timestamp')
        payload = event.get('payload') or {}
        kind = payload.get('type')
        if event.get('type') == 'compacted':
            stats['compactions'] += 1
        if kind == 'function_call':
            calls[payload.get('name')] += 1
        if kind == 'custom_tool_call':
            stats['custom_tool_calls'] += 1
        if event.get('type') == 'event_msg' and kind in ('task_started', 'task_complete', 'turn_aborted'):
            stats['latest_turn_state'] = kind
        if kind == 'message' and payload.get('role') == 'assistant':
            stats['printed_tool_calls'] += int('<tool_call>' in str(payload.get('content')))
        if kind in ('function_call_output', 'custom_tool_call_output'):
            text = str(payload.get('output'))
            stats['zero_exit_property_exceptions'] += int('Process exited with code 0' in text and 'cannot be found on this object' in text)
            stats['constructor_errors'] += text.count('TypeError: not a constructor')
        if kind == 'token_count':
            stats['native_usage'] = (payload.get('info') or {}).get('total_token_usage')
    stats['function_calls'] = dict(calls)
    stats['archive'] = str(ROLLOUT)
    return stats


def write_report(stats):
    content = f'''# 我的 Codex v36：代理、资料搜索与日志改进

## 使用方法

当前旧窗口和任务继续运行。任务结束后关闭旧窗口，再双击桌面“我的Codex”。新入口打开 v36 的“模型与性能”页。

- 页面上方有“开启代理 / 关闭代理”按钮；已经保存你给的 VLESS、WebSocket、TLS 节点，初始状态为开启。
- 点击按钮会重新连接编程引擎，并保留当前对话；执行任务或加载模型期间会等待空闲后再允许切换。
- 模型获得真实的 `search_web` 和 `read_webpage` 工具，可以自己搜索资料、读取正文并引用来源。可以直接告诉它“先查官方文档，再处理这个错误”。
- “选择模型目录”按钮保存新目录。将已有 GGUF 和对应视觉投影文件放在该目录，点击“启动模型”后生效；选择目录不会搬动或复制权重。
- 新程序：`{INSTALL / 'MyCodex.exe'}`。
- 新源码：`{SOURCE}`；原有 v35 程序和源码仍在原路径。

## 最近对话日志的发现

检查的对话：`{ROLLOUT}`。

截至 `{stats.get('last_timestamp')}`，记录了 {sum(stats['function_calls'].values())} 次函数调用、{stats['custom_tool_calls']} 次自定义工具调用、{stats['compactions']} 次上下文压缩。日志检查是运行中的快照。

1. **错误被当成成功。** 两次 PowerShell 返回码为 0，但输出已明确报出 `OutputWritten` / `OutputDataReceived` 属性不存在。新版先识别异常正文，再判断返回码，并保留出错位置。模型会收到该错误证据，避免误记成已完成。
2. **工具调用写成了文字。** 至少一次历史检查点被写成 `<tool_call>` 文本，实际上没有调用。新版要求通过真实工具接口执行，并在对话里标明“工具调用写成文本，尚未执行”。
3. **压缩后可能重复旧方向。** 原始日志中，你先说按钮是手动点的，后来要求自动点；那段文字检查点发生在最新要求之前，不能据此断言模型已经遗忘。新版另外保留最近三条真实用户消息，压缩摘要发生冲突时以最新纠正为准。
4. **遇到陌生接口一直猜。** 最近输出又有 `TypeError: not a constructor`。新版增加实际资料搜索和网页读取，并要求先查接口文档、定位失败机制后再重试。没有直接修改正在执行的 Frida 任务。
5. **思考耗时很长。** 较早的单次请求已超过 400 秒。新版指令要求短计划后进入工具执行；本次没有强制缩短推理预算，没有宣称已经解决所有模型循环。

## 已验证的功能与限制

- 代理配置经 sing-box 官方程序检查通过；监听地址仅为本机，本地模型接口保持直连。
- 实际点击按钮可开启和关闭独立代理进程，编程引擎发现两项网页工具。关闭连接后代理进程和临时配置会清理。
- **打包后的程序**通过该代理搜索到 Python 官方 pathlib 文档，并读取 2200 字符正文；完整检查约 5.6 秒。搜索源为 Bing，DuckDuckGo 本轮没有结果，保留了可用来源。
- 自定义模型目录能保存，文本模型与视觉投影文件路径同步更新。
- 两个真实 PowerShell 异常都能被识别为失败；正常返回码 0 和打印代码列表保持正确识别。
- 搜索与读取网页使用本程序明确选择的网络路径，Windows 全局代理与其他语音服务配置不作修改。
- 本轮 Google 连通性检查返回 204；访问 `api.openai.com` 出现 TLS EOF。因此这次证明了资料搜索可用，不能据此声称所有网站都可达。
- 已验证引擎发现工具和工具实际联网；未在你的运行中对话插入新的模型请求，也未证明模型每次都会主动选择搜索。

检查记录在 `D:\\LocalCodex\\verification-proxy36-*.json`。代理 UUID 只存于本机受限配置，不写进源码或安装包。

## 备份和回退

备份：`{BACKUP}`，包含当前程序、运行组件、源码、配置、对话和日志；SQLite 使用在线快照。校验清单在 `backup-manifest.json`。约 6.06 GB，不重复复制 G 盘模型权重，另有模型文件引用记录。

需要回退时，先结束新版任务并退出窗口，再运行备份目录里的 `恢复v35桌面入口.cmd`。该脚本只恢复桌面入口，原有 v35 程序未覆盖；新版生成的对话继续保留。v35 下次启动会重新生成自己的引擎配置。

## 实现依据

- [Codex MCP 官方配置说明](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)：使用 STDIO 服务和独立工具超时。
- [sing-box VLESS 官方文档](https://sing-box.sagernet.org/configuration/outbound/vless/)与 [WebSocket 配置](https://sing-box.sagernet.org/configuration/shared/v2ray-transport/)。
- [sing-box v1.14.2 官方发布](https://github.com/SagerNet/sing-box/releases/tag/v1.14.2)：下载包 SHA256 已核对发布资产摘要。
'''
    (SOURCE / '日志改进与使用说明-v36.md').write_text(content, encoding='utf-8')
    (ROOT / '日志改进与使用说明-v36.md').write_text(content, encoding='utf-8')


def main():
    manifest = json.loads((BACKUP / 'backup-manifest.json').read_text(encoding='utf-8'))
    if manifest.get('phase') != 'complete':
        raise RuntimeError('Backup is incomplete')
    for suffix in ('button-live', 'engine', 'log-fixes', 'ui-final', 'frozen-mcp'):
        report = json.loads((ROOT / f'verification-proxy36-{suffix}.json').read_text(encoding='utf-8'))
        if not report.get('ok'):
            raise RuntimeError('Verification is incomplete: ' + suffix)
    if INSTALL.exists():
        raise RuntimeError('The new installation directory already exists; inspect before replacing it')
    if not (STAGE / 'MyCodex.exe').is_file() or not (STAGE / '_internal' / 'tools' / 'sing-box.exe').is_file():
        raise RuntimeError('Built application is missing')
    original_shortcut = SHORTCUT.read_bytes()
    (BACKUP / '我的Codex-v35入口.cmd').write_bytes(original_shortcut)
    # Base64 and ASCII code keep this helper reliable on Windows PowerShell 5.1.
    import base64
    encoded = base64.b64encode(str(SHORTCUT).encode('utf-16-le')).decode('ascii')
    # Use an English filename inside the helper, and an English-only script body.
    (BACKUP / 'desktop-v35-original.cmd').write_bytes(original_shortcut)
    restore = ('@echo off\r\nset "CODEXX_BACKUP_DIR=%~dp0"\r\npowershell.exe -NoProfile -Command "'
        + '$p=[Text.Encoding]::Unicode.GetString([Convert]::FromBase64String(\'' + encoded + '\')); '
        + 'Copy-Item -LiteralPath (Join-Path $env:CODEXX_BACKUP_DIR \'desktop-v35-original.cmd\') -Destination $p -Force"\r\n')
    (BACKUP / '恢复v35桌面入口.cmd').write_bytes(restore.encode('ascii'))
    stats = inspect_latest_log()
    write_report(stats)
    (ROOT / '日志检查快照-v36.json').write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding='utf-8')
    shutil.copytree(STAGE, INSTALL)
    staged_files = [path for path in STAGE.rglob('*') if path.is_file()]
    for path in staged_files:
        target = INSTALL / path.relative_to(STAGE)
        if path.stat().st_size != target.stat().st_size or digest(path) != digest(target):
            raise RuntimeError('Installed file verification failed: ' + str(path.relative_to(STAGE)))
    launcher = '@echo off\r\nstart "" "' + str(INSTALL / 'MyCodex.exe') + '" --no-auto-model --show-model-options\r\n'
    SHORTCUT.write_bytes(launcher.encode('ascii'))
    deployment = {'version': '2026-10-07-proxy-model-location-36',
        'installed_at': datetime.now(timezone.utc).isoformat(), 'source': str(SOURCE),
        'exe': str(INSTALL / 'MyCodex.exe'), 'previous_exe': str(OLD), 'backup': str(BACKUP),
        'launcher': str(SHORTCUT), 'activation': 'next desktop launch after the existing task finishes',
        'existing_processes_interrupted': False, 'installed_files': len(staged_files),
        'all_installed_sha256_match': True, 'exe_sha256': digest(INSTALL / 'MyCodex.exe'),
        'proxy_exe_sha256': digest(INSTALL / '_internal' / 'tools' / 'sing-box.exe')}
    (ROOT / 'deployment-proxy36.json').write_text(json.dumps(deployment, ensure_ascii=False, indent=2), encoding='utf-8')
    (WORKSPACE / '当前版本-v36.md').write_text(
        '# 当前使用 v36\n\n新源码：`' + str(SOURCE) + '`。\n\n程序：`' + str(INSTALL / 'MyCodex.exe')
        + '`。\n\n桌面“我的Codex”已更新；任务结束后重开生效。\n\n说明：`'
        + str(ROOT / '日志改进与使用说明-v36.md') + '`。\n\n备份：`' + str(BACKUP) + '`。\n', encoding='utf-8')
    print(json.dumps(deployment, ensure_ascii=False))


if __name__ == '__main__':
    main()
