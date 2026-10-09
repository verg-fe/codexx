# Huihui 自动启动 IDA

2026-10-09：`ida_local.start_ida(target_path)` 已加入 MCP 桥接器。传入现有目标文件的绝对路径，工具通过随附 Python 3.8 启动现有 IDA，并等待本机 MCP 就绪；已有实例时返回当前项目，不重复启动。当前程序实际内核版本为 7.7，安装目录名中的 7.6 不能代表版本。

## 恢复本机配置

- 将 `src/ida_mcp_bridge.py` 复制到 `D:/LocalCodex/tools/ida-mcp/ida_mcp_bridge.py`，沿用本机 `connection.json` 和 `tools.json`；凭据文件不随仓库发布。
- 将 `tools/ida-mcp/Launch-IDA-Huihui.cmd` 放到 `G:/LocalCodex/tools/ida-mcp/`。它固定子进程 Python、用户目录、临时目录和 Qt 软件渲染设置。
- 将技能目录 `skills/r0idamcp-ida-local` 更新到本机 Huihui 技能目录；已有工作台使用 `D:/LocalCodex/codex-home/skills/`。新建对话以刷新工具发现。
- IDA 插件应自动加载（`PLUGIN_FIX | PLUGIN_KEEP`），只监听 `127.0.0.1:26868`。

工作文件、日志和数据库放在 G 盘。IDA 独立程序、许可证、凭据和第三方插件二进制不包含在此次上传中。此前 v70 Release 压缩包不会被本次源码提交自动替换。

## 实测范围

见 `verification/ida-*.json`：冷启动并打开保存的本地测试数据库、重复调用识别已有实例、拒绝不存在的路径，以及 MCP 连接、项目元数据、函数查询、反汇编和 Hex-Rays 原生 x64 反编译均通过。测试函数返回 42。工具发现共 28 项，不代表全部工具或所有处理器都已经验收；Dalvik DEX 的 Hex-Rays 支持不能据此推断。
