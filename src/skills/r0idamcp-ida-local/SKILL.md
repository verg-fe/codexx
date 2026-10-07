---
name: r0idamcp-ida-local
description: 需要在 IDA 中查函数、反编译、查看字符串和交叉引用或修改当前数据库名称和注释时使用。
---

# 本机 IDA MCP

工作台已接入 `ida_local` MCP，提供 27 个 r0idamcp 工具。先在 IDA 打开目标数据库，用 `check_connection` 和 `get_project_metadata` 确认当前文件，再查函数或反编译。`decompile_function` 的地址和名称只能选一种：按地址调用时 `function_name` 传空字符串。

IDA 位于 `G:/IDA Pro v7.6.210427/ida64.exe`，程序实际版本为 7.7.22.0118，使用自带 Python 3.8.10。兼容插件 `plugins/codexx_ida_mcp.py` 在 IDA 内运行，不需要把 FastMCP 安装到 Python 3.8。外部桥接和 schema 位于 `D:/LocalCodex/tools/ida-mcp`；原上游源码在 `G:/r0env2026/reference/r0idamcp`。兼容层已修正旧版 `decompile_func` 的函数对象参数和类型标注转换。

桥接仅监听 `127.0.0.1:26868`，使用本机凭据文件完成认证。不要读取或输出该文件中的 token。连接失败时核实 IDA 是否打开数据库、插件是否加载以及端口所属进程；工具不存在时检查工作台 MCP 配置与启动日志。

重命名、类型和注释工具会修改当前 IDB；需要修改时先备份数据库，再按当前任务操作。接口连通不能代替功能验收；按任务核对实际返回内容。2026-10-08 已实际验证 Huihui 依次调用连接、函数列表和反编译成功。
