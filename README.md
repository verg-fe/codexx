# codexx / 我的 Codex v36

Windows 本地编程工作台：Qwen 本地模型、项目文件、对话历史、原生工具调用、网页资料搜索。

## 最新版本

- 当前维护源码在 `src/`。`legacy-workbench/` 保存以前的部署、诊断与升级资料。
- v36 新增代理一键开关、自定义模型目录、搜索与网页读取工具。
- PowerShell 报错即使返回码为 0 也保留失败证据；提示写成文字而没有执行的工具调用；压缩后保留最近用户纠正。
- [详细使用说明及最近日志分析](docs/日志改进与使用说明-v36.md)。
- [验证记录](verification/)。检查工具实际联网与引擎工具发现，不保证模型每次都主动选择搜索。

## 下载完整文件

仓库的 `v36-20261007` Release 附件提供：

1. `MyCodex-v36-windows.zip`：已打包的新版程序和代理组件。
2. `codexx-workspace-v36.zip`：完整工作目录快照，包含子项目与工具文件，排除构建缓存、凭据和模型权重。
3. `MyCodex-v35-backup-redacted.zip` 或其 `.partNNN` 分卷：升级前完整版本快照，约 6 GB 原始数据，含运行组件、源码、配置、对话、日志及数据库；已知凭据脱敏。
4. `runtime-moe4all.zip`：旧备份若缺少此后端，则单独提供现有运行组件。
5. `current-v36-config-and-reports.zip`：当前设置、启动入口及报告；代理身份凭据与 API 密钥需重新填写。
6. `release-assets-manifest.json`：文件大小及 SHA256；分卷合并后也能校验完整压缩包。

分卷按编号顺序拼接，用附件 `join_release_parts.py` 合并。原始本机备份保持不变；上传副本经过凭据脱敏，原有校验清单代表脱敏前文件，上传文件请以新清单为准。

## 安装与源码运行

原环境为 Windows、AMD RX 9070，工作台目录 `D:\LocalCodex`、模型目录 `G:\LocalCodex\models`。

- 恢复备份 `deployment/` 中需要的引擎、运行时、模板和配置到 `D:\LocalCodex`；不要运行旧升级脚本覆盖新版。
- 将新版程序解压至 `D:\LocalCodex\app\MyCodex-proxy36`，启动 `MyCodex.exe --no-auto-model --show-model-options`。
- GGUF 权重未上传；放入自选目录，在“模型与性能”里选择目录后启动模型。
- `config/proxy-settings.example.json` 是代理配置模板。真实 UUID、API 密钥及账号登录凭据未上传，应在本机重新配置。
- 从源码打包可使用 `src/MyCodex.spec`；先将官方 sing-box Windows 组件放入 `src/tools/`。代理组件和第三方组件的许可见对应包内 LICENSE。

官方资料：[Codex MCP](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)、[sing-box VLESS](https://sing-box.sagernet.org/configuration/outbound/vless/)、[sing-box v1.14.2](https://github.com/SagerNet/sing-box/releases/tag/v1.14.2)。

此仓库按私有仓库创建。上传过程不会关闭当前工作台或模型任务。
