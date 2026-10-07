---
name: github-private-publish
description: 用户要求上传项目、技能或发布程序到其 GitHub 私人仓库时使用；通过已登录的本地 GitHub CLI 上传和核对结果。
---

# 私人仓库上传

本机 GitHub CLI 已连接 `verg-fe` 账号，目标仓库为 `verg-fe/codexx`。工作台子进程可直接调用 `gh`，或使用 `D:/LocalCodex/github-upload-work/gh/bin/gh.exe`。登录保存在系统凭据存储，沿用现有认证；不要读取或输出 token，不把认证文件放入仓库。

先用 `gh repo view verg-fe/codexx --json visibility,nameWithOwner` 核对账号仓库和 PRIVATE 状态。现有源码检出目录为 `D:/LocalCodex/github-upload-work/repo`，发布文件暂存于其同级 `assets`；操作前检查未提交改动，保留已有工作。

在用户要求上传时准备源代码、必要技能、恢复说明和程序包。检查包内文件，剔除真实凭据、许可证密钥、会话日志、临时数据库和缓存；真实设置用占位值模板代替。程序包用 release asset，代码变更使用 git 提交和推送。多行发布说明写入 UTF-8 文件，再传给 `--notes-file`。

大文件先核对 GitHub 当前文件限制、许可和恢复方法。分块清单必须记录原文件大小、完整 SHA256、每块编号、大小和 SHA256；逐块确认远端资产后再清理本轮生成的临时块，不能删除原件。正在运行的虚拟机磁盘需通过一致的快照或停止后的副本备份，且检查副本里的个人凭据和日志。

完成后用 `gh release view` 或仓库提交 API 核对真实远端状态，报告提交或 release URL。遇到认证、权限、容量或 HTTP 错误，保留待上传清单和精确错误，避免无休止重试。下载链接和清单不等于原文件已经上传。
