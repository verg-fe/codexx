---
name: r0idamcp-ida-local
description: 需要在 IDA 中查函数、反编译、查看字符串和交叉引用或修改当前数据库名称和注释时使用。
---

# 本机 IDA MCP

## 运行状态与安全提示

用户指定使用 `G:/IDA Pro v7.6.210427/ida64.exe`。实际文件元数据报告版本 `7.7.22.0118`、发布者字段 `www.52pojie.cn`，未签名，旁边有 `Keygen.7z`。本机 Python 启动报错 `No module named 'imp'` 后，已在其 `python/3/imp.py` 添加基于 `importlib` 的源码兼容层；原目录没有同名文件。补丁先在隔离目录用随附 Python 3.8.10、系统 Python 3.12.10 和 3.14.7 做了 find/load/reload 测试。字节码补丁因 magic number 不匹配已撤回，备份记录在 `G:/LocalCodex-work/mycodex-repair-20261009/backups/ida-imp-compat-20261009`。

初次诊断时的历史状态：PID 3260 标题为“IDA:快速启动”，载入了 `C:\Python314\python314.DLL`，MCP 端口 26868 未监听。该旧状态后来由 G 盘启动器重启验证（PID 8476），再由打开 DEX 的会话（PID 13712）取代；见下方 2026-10-09 更新。此副本未签名，Windows 警告仍由用户自行处理；不要自动点击、移除 Mark-of-the-Web 或更改全局安全设置。

兼容插件在该副本的 `plugins/codexx_ida_mcp.py`，桥接目录为 `D:/LocalCodex/tools/ida-mcp`，只应监听 `127.0.0.1:26868`。插件与 MCP 的实时连通状态以最后一节的验收更新为准；桥接凭据不得读取或输出。

## X Browser APK 限制

测试 APK `com.mmbox.xbrowser`（5.6.4）含 DEX、无原生 `.so`。当前 IDA Pro 副本的 `dex64.dll` 与 Dalvik processor 可加载 DEX version 037，MCP 可读元数据、函数表、字符串和段；IDA 输出 `Unsupported CPU: dalvik`，因此不要声称支持 Dalvik 反编译或伪代码。实际 DEX MCP smoke test 与结果见 G 盘报告。

## MCP 使用规则

连通后先用 `check_connection` 与 `get_project_metadata` 确认当前数据库，再查函数或反编译。`decompile_function` 的地址和名称只能选一种；按地址调用时 `function_name` 传空字符串。重命名、类型和注释工具会修改 IDB；修改前备份，并核对变更结果。

## 2026-10-09 startup repair follow-up (initial pending state; superseded below)

- Runtime diagnosis: the open process (PID 3260) loads `python3.dll` and `python314.DLL` from `C:\Python314`, while IDA's bindings are under its own `python\3\ida_64`. That process therefore did not use the bundled CPython 3.8 runtime. The bundled `G:\IDA Pro v7.6.210427\python38\python.exe` is 3.8.10 and imports the bundled `imp` module successfully.
- Fixed plugin startup: `plugins\codexx_ida_mcp.py` now uses `idaapi.PLUGIN_FIX | idaapi.PLUGIN_KEEP`. IDA SDK documents `PLUGIN_FIX` as loading at IDA startup and retaining the plugin until exit. Source: https://docs.hex-rays.com/8.5/developer-guide/idapython/how-to-create-a-plugin
- Added process-scoped launcher: `G:\LocalCodex-work\mycodex-repair-20261009\artifacts\xbrower-bookmark-chain\Launch-IDA-with-bundled-Python.cmd`. It prepends only the bundled Python 3.8 folder to the child process PATH and clears Python override variables. It does not change machine/user PATH or Windows security settings.
- Backup and hashes: `G:\LocalCodex-work\mycodex-repair-20261009\backups\ida-autoload-python-runtime-20261009\manifest.txt`; original plugin SHA256 `AEE19F151DB01D2CA43D9C9081833C31B536A33F1230BE32780010D66CB7B04B`; patched plugin SHA256 `48F75E403FFC4134D7173816607545E0DEE4EACC21EA443B4D443B2F8266373B`.
- Verified offline: bundled Python 3.8.10 imports `imp.pyc`; patched plugin passes Python 3.8 syntax compilation. Original is backed up on G:.
- Pending live check: current IDA process predates the patch, still has the wrong Python 3.14 DLL loaded, and port 26868 is not listening. A restart through the new launcher is required before checking auto-load and MCP calls. Windows still presents its unsigned-publisher warning; the user must decide in that dialog. No automation or system setting bypasses it.


## 2026-10-09 startup follow-up

The active IDA process now runs through the G: launcher with the bundled Python 3.8 runtime. `python3.dll` and `python38.DLL` were verified under `G:/IDA Pro v7.6.210427/python38`; IDA bindings were verified under `python/3/ida_64`. The MCP plugin uses `PLUGIN_FIX | PLUGIN_KEEP` and starts automatically. Port `127.0.0.1:26868` is listening. The real stdio bridge passed JSON-RPC initialize, tools/list (27 tools), check_connection, and get_project_metadata. The current IDA window has no database loaded, so project-specific functions are not yet verified. See `G:/LocalCodex-work/mycodex-repair-20261009/artifacts/xbrower-bookmark-chain/IDA-startup-repair-2026-10-09.md` and the `ida-mcp-smoke` evidence folder.

The launcher changes only its child process environment; it does not modify global Python settings. The executable is unsigned. If Windows shows the publisher warning, the user must decide in the dialog. Do not automate acceptance or disable the warning.

## 2026-10-09 X Browser DEX acceptance update

- Current IDA instance is PID 13712, running `G:/IDA Pro v7.6.210427/ida64.exe` with `xbrowser-classes.dex` loaded. `127.0.0.1:26868` is listening under this PID. The original saved IDB SHA256 remains `47A24B3074E1C8DA04B6119171537D508526F563018DDE187990C4DDCA45375D`.
- The real MCP stdio bridge passed all 19 annotated read-only tools against this DEX. Seventeen returned useful data. Two correctly surfaced limitations for this target/context: `get_current_function` has no function at cursor `0x0`, and `decompile_function` reports that Hex-Rays is unavailable for this Dalvik DEX. `disassemble_function` works and returns Dalvik bytecode.
- Bookmark evidence: `CREATE TABLE bookmark` defines `_id`, `guid`, `title`, `url` (unique), `parent`, `type`, visits, last_visit, item_order, and status. `x5.O@VL` at `0x744b0` creates this table and an index. `x5.G@ZLIIL` at `0x73614` contains SQL that updates bookmark visit/order fields. `BrowserProvider.b@V` at `0x15b22c` initializes the `content://<package>/bookmark` URI. Full request/response evidence is in `G:/LocalCodex-work/mycodex-repair-20261009/artifacts/xbrower-bookmark-chain/ida-mcp-smoke/bookmark-disasm-*` and `bookmark-semantic-*`.
- Eight mutating MCP tools were not executed. A disposable copy could not be completed because IDA holds the `.id0/.id1/.nam` companions open; no mutating request was sent and the saved original IDB hash is unchanged. Do not claim the write tools passed.
- The overall Android action “add Baidu to X Browser bookmarks” remains incomplete. ADB shell input and UIAutomator injection were denied with Android `INJECT_EVENTS`; do not bypass this with root. The IDA DEX read-only chain is verified, but it is not an end-to-end bookmark action.
- A temporary partial clone directory is present at `G:/LocalCodex-work/mycodex-repair-20261009/artifacts/xbrower-bookmark-chain/ida-write-test-clone`; its three files are copies created during the blocked clone attempt. It was not opened or modified. Keep it separate from the verified original.
- The last launcher start did not show a Windows publisher prompt; this does not mean or imply that the warning was suppressed. Do not auto-accept or weaken Windows security.
