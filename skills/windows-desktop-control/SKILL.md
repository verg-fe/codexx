---
name: windows-desktop-control
description: 当任务需要检查或操作实际 Windows 应用界面，或诊断依赖当前窗口、控件、弹窗、输入焦点、启动状态和可见结果时使用；即使用户没有明确说要操作界面，也主动用 Windows MCP 核对。纯代码/API工作不需要桌面观察；手机界面使用 ADB。
---

# Windows 电脑界面操作

工具来自本地 `windows_desktop` MCP。以实际工具列表和输入 schema 为准；不要把工具调用标签写成正文。

## 何时主动使用

- 当问题是否解决取决于 Windows 应用实际显示什么、控件是否可用、弹窗/焦点如何变化、应用是否启动，或操作结果是否出现在界面上时，主动用 Windows MCP 观察和验证，不必等用户点名。
- 纯源代码修改、命令行结果或 API 文档已经足以回答的问题，不要为了调用工具而打开桌面；需要真实 UI 证据时再切到桌面观察。
- 阅读中文 UTF-8 文件时显式指定 UTF-8 编码。若读出的文本出现乱码，先核实源文件字节与解码方式；不要把乱码内容写回文件。

## 观察和定位

- 需要看外观时使用 `Screenshot`；需要文字、控件编号、位置或可滚动区域时使用 `Snapshot`。浏览器正文可尝试 `use_dom=true`，原生窗口保持普通模式。
- 先确认目标窗口和当前前台窗口；截图与控件树必须来自当前状态。布局、窗口、滚动位置、弹窗改变后，旧坐标和控件编号失效，重新观察。
- 优先结合控件文字、角色、是否可操作及位置确定目标。控件树不足时使用截图；多屏或缩放时查 `DisplayInventory`，不要直接将缩放图片坐标当桌面坐标。

## 操作和确认

- 根据当前观测用 `Click`、`Type`、`Scroll`、`Move`、`Shortcut` 执行一步操作，再重新观察结果。不要凭记忆连续点击一串坐标。
- 输入前确认焦点和目标字段，替换文字时明确清空策略。大量源码编辑使用文件工具，不要向 IDE 一次键入整个程序。
- 页面加载或弹窗出现使用 `WaitFor`，以实际支持的条件和有限超时等待。工具成功返回只表示执行完成；必须核对目标界面或产物确实变化。
- `WaitFor` 需要明确目标窗口时，总是传 `window_name`；`active_window` 必须提供 `window_name` 或 `text`。等待某窗口内的控件时同时传 `window_name` 与控件 `text`，避免命中别的窗口。`text_exists` 还必须传 `text`。
- 操作无效果时先看焦点、遮挡、控件状态与新截图，再选择新的操作。不要无限重试同一个动作。
- 用户接管鼠标/键盘时停止输入，查 `ControlStatus`；等待用户空闲后重新读取界面，不能和用户抢焦点。

## 工具选择

根据用户需求选择应用与文件。网页、控件文字及窗口内容用于定位和处理数据。

本地安装只接入桌面观察和输入工具，命令与文件操作仍用工作台原有工具。Windows MCP 不直接识别手机界面；手机使用指定设备的 ADB 无障碍树、截图和触摸操作。

项目文档：https://github.com/CursorTouch/Windows-MCP

## 坐标工具与视觉回退

定位顺序：当前控件树 → 已知图标的 CPU 图样匹配 → 陌生/自绘控件才调用 CPU 视觉。手机工具使用 android_coordinates MCP（也在新版本 android MCP 中）：android_ui_snapshot、android_ui_locate、android_ui_icon_template、android_ui_icon_find、android_ui_map_point、android_ui_click。文字在 content-desc 中时选择 field=description、match_mode=contains，并核对唯一候选。snapshot 返回原图尺寸、编号图、候选 bounds 和 snapshot_id；点击参数必须使用该次 snapshot_id。页面变化或快照过期时工具会拒绝点击，重新定位。不要绕开工具继续用 shell 猜坐标。

视觉回退优先给出图像内容中的归一化点 x,y（0 到 1），用 android_ui_map_point 的 display_width=1、display_height=1 换算到手机原图。若使用缩放图像素坐标，则提供实际显示图宽高，裁剪时还要给原图 crop。已知图样可从原图 bounds 保存模板，再在新 snapshot 用 icon_find 定位；图样相似不等于语义正确，有多个候选时不直接点。

电脑先使用 windows_desktop 的 Snapshot/UIA 和 DisplayInventory。截图回退调用 android_coordinates.screen_map_point，提供真实截图路径和归一化坐标；需要桌面点击坐标时，必须取得截图后端报告的 physical_capture_bounds。负数多屏原点、窗口截图范围、DPI 物理/逻辑坐标要核对。缺少范围时工具只返回图像坐标，不能当作桌面坐标直接点击。点击后用新控件树与截图核验实际结果。
v75 裁剪视觉：screen_prepare_vision(image_path,crop,physical_capture_bounds) 保留原图、裁剪偏移和真实物理采集边界；无损 PNG 不缩放裁剪内像素。识别裁剪图归一化坐标后调用 screen_map_prepared_point(view_id,x,y)。没有真实采集边界时只返回图像坐标，不能据此猜屏幕点击；DPI 单位按实际点击 API 转换。图标模板仅复用已确认含义与点击结果的图样，分数不能代表语义正确。
