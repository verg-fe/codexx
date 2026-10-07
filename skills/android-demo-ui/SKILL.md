---
name: android-demo-ui
description: 在用户授权的自有 Android 演示或测试 App 上实现和诊断局部界面效果、点击回调、延迟弹窗及可停止 Frida 注入时使用。
---

# 自有 Android 演示界面

先确认用户授权的设备、包名和界面目标，所有探测与修改仅针对该目标。本 skill 不提供对其他 App、后端、账号、支付或系统安全设置的授权。

1. 读当前文件和已有验证记录。每次 attach 前快速核对目标 PID；环境已验证且无变化时不要重做整套安装探测。
2. 点击探测优先使用目标 App 的无障碍树定位控件，并用 ADB 截图核对新鲜画面；按 [references/frida-ui.md](references/frida-ui.md) 的“无障碍树与截图点击”步骤执行。
3. 将界面目标拆成真实事件：目标按钮点击、效果出现、延迟回调、输入界面、停止恢复。点击结果和业务回调是否执行必须分别记录。
3. 出现 bridge、ART、视图类型或日志问题时读 [references/frida-ui.md](references/frida-ui.md)，先定位实际类型与调用链，再选 API。
4. 本例已验证的局部实现位于 [assets/red-flower-demo/hook.js](assets/red-flower-demo/hook.js) 和 [assets/red-flower-demo/inject_demo.py](assets/red-flower-demo/inject_demo.py)。仅作为用户自有红花演示 App 的模板；适配当前目标，不照搬包名、按钮 id、路径和设备参数。
5. 原监听器在替换前保存，停止时在主线程恢复监听、关闭自己创建的弹窗/覆盖层，再卸载脚本和 detach。先确认只有一份注入器；后台进程与客户端断开也要说明实际生命周期。
6. 用户要求实测时检查真实截图、触发日志和两个时间戳。1000ms 定时器不意味着界面恰在1000ms绘制完，应报告实测差值。重复点击以及停止/重载要覆盖。无后端的演示不得读取、保存或发送输入框内容。

不根据单次导入内部模块失败判定客户端损坏；不根据DONE、端口存在或进程存活判定界面成功。故障修复后回到用户要求的界面效果，别反复研究已通过环节。
