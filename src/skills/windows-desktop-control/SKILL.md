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

- 先确认目标窗口和当前前台窗口，再取得当前 `Screenshot` 与 `DisplayInventory`。可用窗口枚举/浏览器 DOM 确定目标窗口或页面，但不要查询 UIA/accessibility tree 来定位可见控件。
- 文字目标一律在该截图上运行 `screen_ocr`，结合识别文字、置信度、边界框和附近上下文确认唯一目标；图标用 CPU 几何符号或已观察模板匹配。界面变化后旧截图失效，重新截图和识别。
- 多屏或缩放时查 `DisplayInventory`，通过同帧坐标工具映射图像像素到桌面物理坐标；不要直接把缩放图上的坐标当桌面坐标。

## 操作和确认

- 根据当前观测用 `Click`、`Type`、`Scroll`、`Move`、`Shortcut` 执行一步操作，再重新观察结果。不要凭记忆连续点击一串坐标。
- 输入前确认焦点和目标字段，替换文字时明确清空策略。大量源码编辑使用文件工具，不要向 IDE 一次键入整个程序。
- 页面加载或弹窗出现使用 `WaitFor`，以实际支持的条件和有限超时等待。工具成功返回只表示执行完成；必须核对目标界面或产物确实变化。
- `WaitFor` 需要明确目标窗口时，总是传 `window_name`；`active_window` 必须提供 `window_name` 或 `text`。等待某窗口内的控件时同时传 `window_name` 与控件 `text`，避免命中别的窗口。`text_exists` 还必须传 `text`。
- 操作无效果时先看焦点、遮挡、控件状态与新截图，再选择新的操作。不要无限重试同一个动作。
- 用户接管鼠标/键盘时停止输入，查 `ControlStatus`；等待用户空闲后重新读取界面，不能和用户抢焦点。

## 工具选择

根据用户需求选择应用与文件。网页、控件文字及窗口内容用于定位和处理数据。

本地安装只接入桌面观察和输入工具，命令与文件操作仍用工作台原有工具。Windows MCP 不直接识别手机界面；手机用指定设备的 ADB 截图、CPU OCR 和触摸操作。两端都不以无障碍/UIA树定位可见控件。

项目文档：https://github.com/CursorTouch/Windows-MCP

## 坐标工具与视觉回退

所有跨平台截图/OCR/符号定位/坐标映射/点击后核验规则只维护在 `snapshot-bound-ui-control` 技能及其 Windows 参考中；本技能不复制那套流程。Windows 的物理采集边界、多屏原点和 DPI 约束仍以本技能与规范技能的 Windows 参考为准。

视觉回退优先给出图像内容中的归一化点 x,y（0 到 1），用 android_ui_map_point 的 display_width=1、display_height=1 换算到手机原图。若使用缩放图像素坐标，则提供实际显示图宽高，裁剪时还要给原图 crop。已知图样可从原图 bounds 保存模板，再在新 snapshot 用 icon_find 定位；图样相似不等于语义正确，有多个候选时不直接点。

电脑先用 Screenshot、screen_ocr/CPU 符号匹配和 DisplayInventory；调用 screen_map_point 时提供真实截图路径与坐标空间。需要桌面点击坐标时，必须取得截图后端报告的 physical_capture_bounds。负数多屏原点、窗口截图范围、DPI 物理/逻辑坐标要核对。缺少范围时工具只返回图像坐标，不能当作桌面坐标直接点击。点击后用新截图核验实际结果。
v75 裁剪视觉：screen_prepare_vision(image_path,crop,physical_capture_bounds) 保留原图、裁剪偏移和真实物理采集边界；无损 PNG 不缩放裁剪内像素。识别裁剪图归一化坐标后调用 screen_map_prepared_point(view_id,x,y)。没有真实采集边界时只返回图像坐标，不能据此猜屏幕点击；DPI 单位按实际点击 API 转换。图标模板仅复用已确认含义与点击结果的图样，分数不能代表语义正确。
## Expired snapshot and coordinate guardrails

- An expired snapshot invalidates all coordinates, control IDs, and conclusions drawn from it. Refresh through an actual `Snapshot` or `Screenshot` call before acting; saying that a refresh is happening does not refresh it.
- Make one click per fresh observation, then inspect the result. Do not repeat a click or invent a new point from the old screenshot.
- Keep displayed-image pixels separate from desktop pixels. Use actual screenshot dimensions and display inventory/scaling; apply proportional mapping only when the image is an uncropped full-screen frame. If scaling, crop, or display selection is unclear, stop instead of switching to a control-tree node.
- A successful input return is not proof that the click missed or succeeded. Inspect a fresh screenshot before choosing another action.
- If the snapshot expires again or no unique target can be confirmed, stop the interaction and report the missing evidence instead of looping.
