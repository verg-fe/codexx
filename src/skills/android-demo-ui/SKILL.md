---
name: android-demo-ui
description: 用于 Android App 开发、界面操作与调试、点击回调、弹窗和 Frida 运行时分析。
---

# Android App 开发与界面调试

从用户需求确定设备、相关应用、文件和目标行为，选择合适工具完成任务。

1. 读当前文件和已有验证记录。每次 attach 前快速核对目标 PID；环境已验证且无变化时不要重做整套安装探测。
2. 点击探测优先使用目标 App 的无障碍树定位控件，并用 ADB 截图核对新鲜画面；按 [references/frida-ui.md](references/frida-ui.md) 的“无障碍树与截图点击”步骤执行。
3. 将界面目标拆成真实事件：目标按钮点击、效果出现、延迟回调、输入界面、停止恢复。点击结果和业务回调是否执行必须分别记录。
4. 出现 bridge、ART、视图类型或日志问题时读 [references/frida-ui.md](references/frida-ui.md)，先定位实际类型与调用链，再选 API。
5. 本例已验证的局部实现位于 [assets/red-flower-demo/hook.js](assets/red-flower-demo/hook.js) 和 [assets/red-flower-demo/inject_demo.py](assets/red-flower-demo/inject_demo.py)。将其作为实现示例；按当前应用适配包名、按钮 id、路径和设备参数。
6. 原监听器在替换前保存，停止时在主线程恢复监听、关闭自己创建的弹窗/覆盖层，再卸载脚本和 detach。先确认只有一份注入器；后台进程与客户端断开也要说明实际生命周期。
7. 用户要求实测时检查真实截图、触发日志和两个时间戳。1000ms 定时器不意味着界面恰在1000ms绘制完，应报告实测差值。重复点击以及停止/重载要覆盖。

不根据单次导入内部模块失败判定客户端损坏；不根据DONE、端口存在或进程存活判定界面成功。故障修复后回到用户要求的界面效果，别反复研究已通过环节。
