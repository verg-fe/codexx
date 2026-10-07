# Windows 与运行状态中的已知陷阱

- PowerShell 执行变量中的程序路径必须 `& $exe ...`；`$exe -s` 是表达式错误。字符串里的变量紧邻冒号用 `${value}:` 或格式化字符串。
- `\"` 不是 PowerShell 的引号转义。跨 PowerShell / ADB / Android shell 多层命令优先写 Python 文件，用 subprocess 参数列表调用。远程 shell 命令仍需按远程 shell 规则引用。
- Magisk su 会解析后续 `-c`、`-n`，用 `su -c '完整命令'`；能使用普通 `am start -n 目标组件` 时无需提权。只操作授权目标。
- 管道使用明确 UTF-8；Python 子进程可用 `-u -X utf8`。PowerShell 5.1 读取含中文的脚本时使用 UTF-8 BOM。终端乱码先核对原文件或ASCII JSON，别误修本来正确的数据。
- `for line in proc.stdout` 内检查期限，不能限制无新输出的等待。读输出线程+队列 get(timeout) 或原生超时；超时要释放子进程和资源。别在打印退出消息后立即terminate仍在正常收尾的进程，先等待正常退出。
- 输出 `rc=0` 不表示 stderr 中没有错误。检查返回码、错误内容与用户目标事件。错误被console.log捕获后也应使验证失败。
- 长时间思考期间观察新token/日志时间戳和真实进程；不要仅按整轮经过时间停止工作。
