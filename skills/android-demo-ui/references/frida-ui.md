# 这次演示实际验证过的经验（2026-10-07）

官方接口：https://frida.re/docs/javascript-api/ 。版本变化时重新核对。

## Bridge 与日志

Frida 17的原始create_script不一定含Java全局。本机用已安装frida_tools/bridges/java.js，其导出是bridge，赋globalThis.Java=bridge，再50ms后Script.evaluate用户脚本。检查实际bridge文件而非猜导出名，不输出整份压缩源码。

公开验证用import frida、get_usb_device、enumerate_processes/目标enumerate_applications。别因顶层import _frida失败认定公开客户端不可用。本机Script只有exports_sync，没有exports_async；读实际客户端再选调用方式。exports_sync等待要有外层有界机制，并确保超时释放脚本。

console.log通过Script.set_log_handler(level,text)，不是message回调的console分支。检查器必须真正接收日志才能判断HOOK_READY。

## 目标界面与类型

本例包com.redqueen.fridaflowerdemo，MainActivity，按钮id2130771969。目标按钮performClick返回true，却没有调用onLoginSuccess，因此只hook该方法不会实现按钮效果。这是本例证据，不能泛化到所有App。

MIUI该构建的ActivityThread.mCurrentActivity是String，不是Activity；Java.choose目标MainActivity后retain，在Java.scheduleOnMainThread操作视图。findViewById泛型结果在该bridge里必须cast View，再调用其方法。容器cast ViewGroup/FrameLayout；接口对象要打印getClass可先cast Object。

setOnClickListener要求Java OnClickListener实例；用Java.registerClass({name,implements:[Java.use('android.view.View$OnClickListener')],methods:{onClick}})并$new，不能传JS普通对象。View.mListenerInfo.value内部的mOnClickListener.value或反射获取才是原监听，直接读View.mOnClickListener得到null/undefined不说明没有监听。

Java enum/静态数值字段取.value；int数组Java.array('int',[0,0])；颜色用signed int。这个bridge的CharSequence参数需要Java String实例，裸JS字符串会导致setText/setHint/setTitle重载错误。保存/替换前的原监听，恢复后明确确认。

## 故障诊断

本例Vector对目标App启用fakepers的作用域造成Frida Java初始化ART abort，日志method_index/num_methods mismatch。当时通过调整目标包作用域处理，并保留恢复记录。不要遇到任何Java失败就禁用模块；先取目标PID的有界crash日志，根据证据选择所需调整。

## 验收

启动器可停止持续存活，真实root触屏点击触发黑花，1000ms定时器后弹窗，实测1170/1165ms；停止后LISTENER_RESTORED与RESTORE_CONFIRMED true，退出0。截图只证明当时画面，不证明长期运行。探测结束要清理；交付时确保持续实例实际启动且不重复。

## Screenshot/OCR UI evidence

Visible Android control targeting is defined by the single snapshot-bound-ui-control skill. Take a fresh screenshot, run CPU OCR on that exact frame for text or CPU symbol/template matching for glyphs, map through the same snapshot, make one guarded click, then verify with a fresh screenshot. Do not use UIAutomator/accessibility-tree tools or raw ADB taps to locate or activate visible controls. Check package, foreground activity, PID and bounded logcat separately when diagnosing runtime behavior.
