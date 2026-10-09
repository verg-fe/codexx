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

## 点击定位与失败恢复

- 先调用 android_accessibility_tree 和 android_screenshot，使用当前控件的 resource-id、text 或 content-desc 匹配唯一目标；从最新 bounds 取中心坐标。文字节点不可点击时找包含它的可点击祖先，不点其他聊天条目来试坐标。
- 自绘控件没有树节点时，读取原始 PNG 宽高并核对显示图是否缩放或裁剪。只有已知缩放比例和裁剪偏移才可换算截图坐标到设备坐标；不知道映射就重新获取原始截图。不能把缩放图片上的坐标直接交给 input tap。
- 每次点击、返回、取消、滚动或键盘弹出后，重新检查树与截图，并以预期页面、目标标题或控件变化判断是否成功。命令退出码 0 只表示输入命令执行，不能宣称进入聊天或返回成功。
- 用户说“没点上”时，将上一动作标记为失败；重新读取当前页面再定位，不基于原先假定的页面继续。KEYCODE_BACK 可能只关闭键盘或先改变焦点，必须检查结果。
- 同一目标连续两次未达到预期状态就停止盲目点击，保留截图和树，诊断焦点、遮挡、实际坐标映射或输入权限；禁止通过改变 y 值反复猜位置。普通触屏点击优先 input tap，不使用未经设备触摸协议核对的 sendevent 序列。
- 上下文压缩只保留目标、最后已验证页面、失败动作和证据路径；恢复执行时先刷新画面和树。旧截图坐标不得当作当前坐标，页面状态不明确时不得进行发送、确认或位置共享等操作。

## 坐标工具与视觉回退

### 默认先读内容，不先读像素（v74）

陌生符号的裁剪回退（v75）：android_ui_prepare_vision(snapshot_id,crop,reason) 将新快照的目标附近裁成无损 PNG，保留原图与偏移，不缩放裁剪内像素。view_image 只打开返回的 image_path。以裁剪图内容为基准给归一化 x,y，用 android_ui_map_prepared_point(view_id,x,y) 获取 snapshot_id 和 device_point，再 android_ui_click 检查当前页面并点击。不要把裁剪图点直接拿去 shell tap。裁剪不能移除判别符号需要的周边信息；找不到区域时可以保留全图，不能猜裁剪边界。

模板并非预先全知：先读文字/描述，陌生符号才进行首次视觉识别；必须核对实际点击结果再将图样作为已确认目标复用。主题/尺寸变化、多个相似图样、低分都应重新确认。分数高也不能证明含义正确。

想知道当前页面有什么，调用 android_ui_snapshot；android_screenshot 也会返回当前控件文字、描述、候选坐标和 snapshot_id。先读清单，不先调用 view_image。未标注控件和自绘区域的含义仍然未知，不能据清单编造图标含义。

控件找不到目标时先匹配已知模板；陌生符号、自绘地图等才调用 android_ui_request_vision(image_path, reason)，说明控件/模板为什么不够，然后用 view_image 打开同一路径。允许有效期 180 秒，绑定原图哈希；更换图片要重新请求。默认手机工具截图经网关转成控件清单，用户直接上传的图片不受此规则影响。不得改用 shell input tap 猜点来绕过控件定位。

定位顺序：当前控件树 → 已知图标的 CPU 图样匹配 → 陌生/自绘控件才调用 CPU 视觉。手机工具使用 android_coordinates MCP（也在新版本 android MCP 中）：android_ui_snapshot、android_ui_locate、android_ui_icon_template、android_ui_icon_find、android_ui_map_point、android_ui_click。文字在 content-desc 中时选择 field=description、match_mode=contains，并核对唯一候选。snapshot 返回原图尺寸、编号图、候选 bounds 和 snapshot_id；点击参数必须使用该次 snapshot_id。页面变化或快照过期时工具会拒绝点击，重新定位。不要绕开工具继续用 shell 猜坐标。

视觉回退优先给出图像内容中的归一化点 x,y（0 到 1），用 android_ui_map_point 的 display_width=1、display_height=1 换算到手机原图。若使用缩放图像素坐标，则提供实际显示图宽高，裁剪时还要给原图 crop。已知图样可从原图 bounds 保存模板，再在新 snapshot 用 icon_find 定位；图样相似不等于语义正确，有多个候选时不直接点。

电脑先使用 windows_desktop 的 Snapshot/UIA 和 DisplayInventory。截图回退调用 android_coordinates.screen_map_point，提供真实截图路径和归一化坐标；需要桌面点击坐标时，必须取得截图后端报告的 physical_capture_bounds。负数多屏原点、窗口截图范围、DPI 物理/逻辑坐标要核对。缺少范围时工具只返回图像坐标，不能当作桌面坐标直接点击。点击后用新控件树与截图核验实际结果。
