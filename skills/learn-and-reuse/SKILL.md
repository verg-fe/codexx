---
name: learn-and-reuse
description: 在任务中发现可复用方法、解决环境错误、形成总结，或需要下载和安装依赖时使用；将已验证经验保存为可更新技能，跨会话复用本机工具。
---

# 学习和复用

用 `skill_search` 检索相关主题，再用 `skill_read` 读取具体技能。下载 SDK、Gradle、Python 库、源码归档或工具前，先核对技能记录的路径、版本和必需文件；新会话工作目录为空不代表本机没有环境。兼容的现有安装直接复用，只有缺失组件或版本不合适时才补充下载。

形成有用总结或验证一项修复后，可以立即调用 `skill_save`。正文记录具体触发问题、有效做法、关键路径、版本、核对结果及容易踩的坑；本次任务的未完成工作仍保留在 `history_checkpoint`。原始日志、密码和访问密钥不写进技能。

已有技能先读取，再合并新结论，保存时传当前 `revision` 为 `expected_revision`。冲突后重新读取合并，不强行覆盖。每次更新自动保存旧版，下一次 `skill_search` / `skill_read` 即可看到新内容，无需重新下载安装技能。

`resources` 可以记录本机安装目录和 `check_files`，读取时工具会返回文件是否仍在。目录存在不能证明版本或所有功能可用；按当前任务核对对应可执行文件和版本。

中文技能优先通过 `skill_read` 读取，普通文本用 `local_read_text`（识别 UTF-8、UTF-16 BOM 和 GB18030），短 PowerShell 文本命令用 `local_run_utf8`。PNG 等二进制数据用 Python `subprocess` 参数列表和字节文件写入；Windows PowerShell 5.1 的 `>` 会把二进制输出写坏。不要对正常中文或不可恢复的乱码做猜测式转码。
